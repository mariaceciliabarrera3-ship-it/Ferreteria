"""Autenticación: login, logout, perfil.

Cambios de auditoría aplicados aquí:

- **ARQ-08**: el límite de intentos fallidos ya no vive en un diccionario del
  proceso: se apoya en la tabla ``login_attempts`` (migración 002), con ventana
  y bloqueo temporal configurables.
- **ARQ-10**: el cierre de sesión pasó de GET a **POST con CSRF**.
- **ARQ-13**: el parámetro ``next`` ya no acepta ``//host`` ni ``/\\host``
  (redirección abierta); sólo se admiten rutas internas de la aplicación.
"""
from urllib.parse import urlparse

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)

from . import config as cfg
from .db import execute, now_iso, query
from .security import (audit, clear_login_failures, current_user, hash_password,
                       login_failures, login_locked, register_login_failure,
                       verify_password)

bp = Blueprint("auth", __name__)


def safe_next(candidate: str | None, fallback: str | None = None) -> str:
    """Devuelve una ruta interna segura o el destino por omisión.

    ARQ-13: ``startswith('/')`` no alcanza. ``//evil.com`` y ``/\\evil.com``
    son rutas "absolutas" relativas al protocolo y el navegador las interpreta
    como otro host: eso era una redirección abierta lista para phishing.
    """
    if fallback is None:
        fallback = url_for("main.dashboard")
    if not candidate:
        return fallback
    candidate = candidate.strip()
    if not candidate.startswith("/") or candidate.startswith("//") or candidate.startswith("/\\"):
        return fallback
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return fallback
    return candidate


@bp.route("/configurar-inicial", methods=["GET", "POST"])
def configurar_inicial():
    """Primer arranque con FERREGEST_SETUP_WIZARD=1: la dueña elige su
    propio usuario, nombre y contraseña en vez de recibir un ``admin``
    con clave generada. Sólo funciona mientras no exista ningún usuario;
    una vez creado el primero, esta pantalla vuelve a /login para siempre.
    """
    n_users = query("SELECT COUNT(*) AS c FROM users", one=True)["c"]
    if n_users > 0:
        return redirect(url_for("auth.login"))

    from .security import ensure_csrf

    ensure_csrf()
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()[:120]
        username = (request.form.get("username") or "").strip().lower()[:64]
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""
        errores = []
        if not full_name:
            errores.append("Ingrese su nombre.")
        if not username or len(username) < 3:
            errores.append("El usuario debe tener al menos 3 caracteres.")
        if len(password) < 8:
            errores.append("La contraseña debe tener al menos 8 caracteres.")
        if password != password2:
            errores.append("Las contraseñas no coinciden.")
        if password and password.lower() in ("admin123", "12345678", "password", username):
            errores.append("Elija una contraseña menos predecible.")
        if errores:
            for e in errores:
                flash(e, "error")
            return render_template("configuracion_inicial.html",
                                   full_name=full_name, username=username), 400

        execute(
            "INSERT INTO users (username, password_hash, full_name, role, perms, created_at) "
            "VALUES (?, ?, ?, 'administrador', '{}', ?)",
            (username, hash_password(password), full_name, now_iso()),
        )
        user = query("SELECT * FROM users WHERE username = ?", (username,), one=True)
        session.clear()
        session["user_id"] = user["id"]
        session.permanent = True
        ensure_csrf()
        audit("usuario_inicial_creado", "usuario", user["id"], {"username": username})
        flash(f"Bienvenida, {full_name}. Su cuenta quedó creada.", "ok")
        return redirect(url_for("main.dashboard"))

    return render_template("configuracion_inicial.html", full_name="", username="")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if cfg.setup_wizard():
        n_users = query("SELECT COUNT(*) AS c FROM users", one=True)["c"]
        if n_users == 0:
            return redirect(url_for("auth.configurar_inicial"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()[:64]
        password = request.form.get("password") or ""
        if login_locked(username):
            audit("login_bloqueado", "usuario", None, {"username": username})
            flash(f"Cuenta bloqueada temporalmente por intentos fallidos "
                  f"({cfg.LOGIN_MAX_ATTEMPTS} en {cfg.LOGIN_WINDOW_MINUTES} min). "
                  f"Espere {cfg.LOGIN_LOCKOUT_MINUTES} min o contacte al administrador.",
                  "error")
            return render_template("login.html"), 429
        user = query("SELECT * FROM users WHERE username = ? AND active = 1", (username,), one=True)
        if user is None or not verify_password(user["password_hash"], password):
            register_login_failure(username)
            audit("login_fallido", "usuario", None,
                  {"username": username, "intentos": login_failures(username)})
            flash("Usuario o contraseña incorrectos.", "error")
            return render_template("login.html"), 401
        clear_login_failures(username)
        session.clear()
        session["user_id"] = user["id"]
        session.permanent = True
        from .security import ensure_csrf

        ensure_csrf()
        audit("login", "usuario", user["id"], {"username": username})
        return redirect(safe_next(request.args.get("next") or request.form.get("next")))
    if current_user():
        return redirect(url_for("main.dashboard"))
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    """Cierra la sesión. ARQ-10: POST + CSRF (un GET no debe cambiar estado)."""
    u = current_user()
    if u:
        audit("logout", "usuario", u["id"], {})
    session.clear()
    flash("Sesión cerrada correctamente.", "ok")
    return redirect(url_for("auth.login"))


@bp.route("/perfil", methods=["GET", "POST"])
def perfil():
    u = current_user()
    if u is None:
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        actual = request.form.get("actual") or ""
        nueva = request.form.get("nueva") or ""
        if len(nueva) < 8:
            flash("La contraseña nueva debe tener al menos 8 caracteres.", "error")
        elif not verify_password(u["password_hash"], actual):
            flash("La contraseña actual es incorrecta.", "error")
        elif nueva in ("admin123", "vendedor123", "deposito123", "12345678", "password"):
            flash("Esa contraseña está en la lista de claves inseguras conocidas. "
                  "Elija otra.", "error")
        else:
            execute("UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(nueva), u["id"]))
            audit("cambiar_clave", "usuario", u["id"], {})
            flash("Contraseña actualizada correctamente.", "ok")
        return redirect(url_for("auth.perfil"))
    return render_template("perfil.html")
