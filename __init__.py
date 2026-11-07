"""FerreGest AR — factoría de la aplicación Flask.

Cambios de auditoría aplicados aquí:

- **ARQ-02**: la ruta de la base se guarda en ``app.config['FERREGEST_DB']``.
  Ya no se modifica ``os.environ['FERREGEST_DB']``, así que dos instancias
  creadas en el mismo proceso pueden apuntar a dos bases distintas sin
  pisarse.
- **ARQ-03**: el ``context_processor`` usa ``lic.get_state()`` (sólo lectura).
  Renderizar una página ya no genera escrituras en SQLite.
- **ARQ-04/ARQ-14/ARQ-15**: el modo de ejecución se expone a las plantillas, se
  envían cabeceras de seguridad y la sesión tiene duración acotada.
- **ARQ-16**: el handler de 500 no devuelve stack traces al navegador.
"""
import os
import secrets
from datetime import datetime, timedelta

from flask import Flask, g, jsonify, redirect, render_template, request, url_for

from . import config as cfg
from . import db as dbm
from . import license as lic
from .money import D, q2
from .security import check_csrf, current_user, ensure_csrf, secret_key, user_perms


def fmt_money(x) -> str:
    """Formato argentino estable, con redondeo decimal (ARQ-09)."""
    try:
        v = q2(x)
    except Exception:
        return "$ 0,00"
    s = f"{abs(v):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return ("-$ " if v < 0 else "$ ") + s


def fmt_qty(x) -> str:
    try:
        v = float(x or 0)
    except (TypeError, ValueError):
        return "0"
    if v == int(v):
        return str(int(v))
    return f"{v:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def fmt_date(iso) -> str:
    if not iso:
        return "—"
    s = str(iso)
    try:
        if len(s) >= 19:
            dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%d/%m/%Y %H:%M")
        dt = datetime.strptime(s[:10], "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        return s


def create_app(db_path: str | None = None) -> Flask:
    # ARQ-02: nada de os.environ global; la ruta vive en la instancia.
    resolved_db = cfg.resolve_db_path(db_path)

    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config["FERREGEST_DB"] = resolved_db
    app.config["FERREGEST_MODE"] = cfg.mode()
    app.config["SECRET_KEY"] = secret_key()
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    # ARQ-15: sesión acotada (8 h por defecto), no "eterna".
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=cfg.SESSION_HOURS)
    app.config["JSON_AS_ASCII"] = False
    # ARQ-14: por defecto la aplicación no se deja incrustar en iframes de
    # otros orígenes. Vaciar FERREGEST_FRAME_ANCESTORS lo habilita (sólo si
    # alguien lo decide con conocimiento, p. ej. detrás de un portal propio).
    app.config["FERREGEST_FRAME_ANCESTORS"] = os.environ.get(
        "FERREGEST_FRAME_ANCESTORS", "'self'")

    with app.app_context():
        dbm.migrate(resolved_db)
        _bootstrap()

    app.teardown_appcontext(dbm.close_db)

    @app.before_request
    def _before():
        if request.method == "POST":
            check_csrf()
        ensure_csrf()

    @app.after_request
    def _security_headers(resp):
        """ARQ-14: cabeceras de seguridad básicas (defensa en profundidad)."""
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        ancestors = app.config.get("FERREGEST_FRAME_ANCESTORS", "'self'")
        if ancestors:
            resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        csp = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "object-src 'none'; base-uri 'self'; form-action 'self'"
        )
        if ancestors:
            csp += "; frame-ancestors " + ancestors
        resp.headers.setdefault("Content-Security-Policy", csp)
        if g.get("user") is not None or request.path.startswith("/pos"):
            # Datos comerciales: no cachear en el navegador compartido.
            resp.headers.setdefault("Cache-Control", "no-store, must-revalidate")
        return resp

    @app.context_processor
    def _ctx():
        u = current_user()
        lic_state = lic.get_state()          # ARQ-03: lectura pura, sin escrituras
        return {
            "current_user": u,
            "user_perms": user_perms(u) if u else set(),
            "license_state": lic_state,
            "csrf_token": session_csrf(),
            "now_year": datetime.now().year,
            "app_mode": lic_state.get("mode", cfg.mode()),
            "is_production": cfg.is_production(),
        }

    @app.template_filter("money")
    def _money(x):
        return fmt_money(x)

    @app.template_filter("qty")
    def _qty(x):
        return fmt_qty(x)

    @app.template_filter("fecha")
    def _fecha(x):
        return fmt_date(x)

    @app.errorhandler(403)
    def _forbidden(e):
        msg = getattr(e, "description", None) or "No tiene permisos para esta acción."
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": msg}), 403
        return render_template("error.html", code=403, message=msg), 403

    @app.errorhandler(400)
    def _bad(e):
        msg = getattr(e, "description", None) or "Solicitud inválida."
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": msg}), 400
        return render_template("error.html", code=400, message=msg), 400

    @app.errorhandler(404)
    def _nf(e):
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": "No encontrado."}), 404
        return render_template("error.html", code=404, message="Página no encontrada."), 404

    @app.errorhandler(409)
    def _conflict(e):
        msg = getattr(e, "description", None) or "Conflicto de datos."
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": msg}), 409
        return render_template("error.html", code=409, message=msg), 409

    @app.errorhandler(401)
    def _unauth(e):
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": "Debe iniciar sesión."}), 401
        return redirect(url_for("auth.login"))

    @app.errorhandler(500)
    def _server_error(e):
        """ARQ-16: nunca devolver el traceback al navegador.

        El detalle queda en el log del servidor; la usuaria ve un mensaje útil
        y el id de incidente para poder informarlo.
        """
        app.logger.exception("Error no controlado: %s", e)
        incident = secrets.token_hex(4)
        msg = (f"Ocurrió un error inesperado (incidente {incident}). "
               "Sus datos no se perdieron: vuelva a intentar o reinicie la aplicación.")
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": msg, "incident": incident}), 500
        return render_template("error.html", code=500, message=msg), 500

    from .bp_auth import bp as bp_auth
    from .bp_main import bp as bp_main
    from .bp_pos import bp as bp_pos
    from .bp_products import bp as bp_products
    from .bp_purchases import bp as bp_purchases
    from .bp_admin import bp as bp_admin
    from .bp_reports import bp as bp_reports

    app.register_blueprint(bp_auth)
    app.register_blueprint(bp_main)
    app.register_blueprint(bp_pos)
    app.register_blueprint(bp_products)
    app.register_blueprint(bp_purchases)
    app.register_blueprint(bp_admin)
    app.register_blueprint(bp_reports)

    return app


def session_csrf():
    from flask import session

    return session.get("csrf", "")


def _bootstrap():
    """Primer arranque: licencia local, unidades por defecto y admin inicial."""
    n_users = dbm.query("SELECT COUNT(*) AS c FROM users", one=True)["c"]
    if n_users == 0:
        from .security import hash_password

        env_pw = os.environ.get("FERREGEST_ADMIN_PASSWORD", "").strip()
        if env_pw:
            pw = env_pw
        elif cfg.is_production():
            # En producción nunca se crea una clave conocida: se genera y se
            # guarda en var/ (fuera del repositorio) para que la dueña la use.
            pw = secrets.token_urlsafe(16)
            _guardar_clave_inicial(pw)
        else:
            pw = "admin123"   # sólo en modo demo (documentado y avisado)
            print("AVISO DE SEGURIDAD: se creó el usuario 'admin' con la clave de "
                  "demostración 'admin123'. Cámbiela en Mi cuenta antes de cargar "
                  "datos reales o defina FERREGEST_ADMIN_PASSWORD.", flush=True)
        dbm.execute(
            "INSERT INTO users (username, password_hash, full_name, role, perms, created_at) "
            "VALUES (?, ?, ?, 'administrador', '{}', ?)",
            ("admin", hash_password(pw), "Administrador", dbm.now_iso()),
        )
        if env_pw:
            print("Usuario 'admin' creado con la clave definida en FERREGEST_ADMIN_PASSWORD.",
                  flush=True)
    n_units = dbm.query("SELECT COUNT(*) AS c FROM units", one=True)["c"]
    if n_units == 0:
        for u in ("unidad", "metro", "caja", "paquete", "rollo", "kilo", "litro",
                  "bolsa", "juego", "docena", "par", "tonelada", "galon", "saco"):
            dbm.execute("INSERT OR IGNORE INTO units (name) VALUES (?)", (u,))
    dbm.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES "
        "('business_name', 'Ferretería Demo'), "
        "('business_address', ''), ('business_cuit', ''), ('business_iva', ''), "
        "('ticket_footer', 'Gracias por su compra'), ('currency', 'ARS'), "
        "('date_format', 'dd/MM/yyyy'), ('demo_mode', '1')"
    )
    lic.get_install_id(create=True)
    # ARQ-03: el chequeo se registra una vez, al arrancar (no por cada GET).
    lic.record_check()


def _guardar_clave_inicial(pw: str):
    """Guarda la clave inicial generada en var/ (0600), nunca en el repositorio."""
    try:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        d = os.path.join(base, "var")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "clave_inicial_admin.txt")
        umask = os.umask(0o077)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"usuario: admin\nclave inicial: {pw}\n")
        finally:
            os.umask(umask)
        print(f"Se generó una clave inicial de administrador. Guárdela en un lugar "
              f"seguro: {path}", flush=True)
    except OSError:
        print(f"No se pudo guardar la clave inicial. Anótela ahora: {pw}", flush=True)
