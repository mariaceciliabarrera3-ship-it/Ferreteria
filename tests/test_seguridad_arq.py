"""FerreGest AR — pruebas de seguridad de la auditoría (ARQ-01 a ARQ-16).

Ejecutar:  python3 -m pytest tests/test_seguridad_arq.py -v
"""
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import ADMIN_PW, ADMIN_USER, BASE, csrf_of, login, nuevo_producto, vender

PAYLOAD = '<img src=x onerror=alert(1)>'


# ============================================================== ARQ-01 — XSS
def test_arq01_js_no_usa_innerhtml():
    """Ningún script vuelve a insertar HTML armado con datos (estático)."""
    patron = re.compile(r"\w\.innerHTML\s*=")
    revisados = 0
    for raiz, _, archivos in os.walk(os.path.join(BASE, "app")):
        for nombre in archivos:
            if not nombre.endswith((".js", ".html")):
                continue
            ruta = os.path.join(raiz, nombre)
            with open(ruta, encoding="utf-8") as fh:
                for i, linea in enumerate(fh, 1):
                    if linea.strip().startswith(("//", "*", "/*")):
                        continue
                    assert not patron.search(linea), (
                        f"ARQ-01: {os.path.relpath(ruta, BASE)}:{i} vuelve a usar innerHTML")
            revisados += 1
    assert revisados >= 5, "se esperaba revisar los JS y las plantillas"


def test_arq01_escape_helper_presente():
    with open(os.path.join(BASE, "app", "static", "app.js"), encoding="utf-8") as fh:
        app_js = fh.read()
    assert "function escapeHtml(" in app_js
    assert "function el(" in app_js
    with open(os.path.join(BASE, "app", "static", "pos.js"), encoding="utf-8") as fh:
        pos_js = fh.read()
    assert "textContent" in pos_js
    assert not re.search(r"\w\.innerHTML\s*=", pos_js), "pos.js volvió a usar innerHTML"


def test_arq01_arnes_dom_en_node():
    """El arnés Node ejecuta app.js y pos.js contra un DOM y un payload real."""
    if shutil.which("node") is None:
        pytest.skip("Node no está instalado: se omite la prueba de DOM")
    proc = subprocess.run(["node", os.path.join(BASE, "tests", "js", "xss_harness.js")],
                          capture_output=True, text=True, cwd=BASE)
    assert proc.returncode == 0, f"el arnés detectó XSS:\n{proc.stdout}\n{proc.stderr}"


def test_arq01_producto_y_cliente_hostil_se_renderiza_como_texto(client):
    """El payload se guarda tal cual, pero en el HTML se muestra escapado."""
    csrf = login(client)
    nuevo_producto(client, csrf, code="XSS-1", description=PAYLOAD, precio=10, stock=5)
    r = client.post("/clientes/nuevo", data={
        "_csrf": csrf, "name": PAYLOAD, "doc": "20-12345678-9", "phone": "",
        "email": "", "address": "", "credit_limit": "0", "notes": "",
    }, follow_redirects=False)

    html = client.get("/productos?q=" + PAYLOAD).data.decode()
    assert "<img src=x" not in html, "el navegador interpretaría el payload"
    assert "&lt;img src=x" in html, "el payload debe mostrarse como texto visible"

    html_clientes = client.get("/clientes").data.decode()
    assert "<img src=x" not in html_clientes
    assert "&lt;img src=x" in html_clientes

    # La API devuelve el dato crudo (es JSON: el escape lo hace el cliente JS).
    data = client.get("/api/buscar?q=" + PAYLOAD[:8]).get_json()
    assert any(PAYLOAD == p["description"] for p in data["productos"])
    assert any(PAYLOAD == c["name"] for c in data["clientes"])


# ===================================================== ARQ-02 — bases aisladas
def test_arq02_dos_instancias_con_dos_bases(tmp_path):
    from app import create_app
    from app.db import execute, query

    db1 = str(tmp_path / "a.db")
    db2 = str(tmp_path / "b.db")
    os.environ.pop("FERREGEST_DB", None)

    app1 = create_app(db1)
    app2 = create_app(db2)
    assert app1.config["FERREGEST_DB"] == db1
    assert app2.config["FERREGEST_DB"] == db2
    assert "FERREGEST_DB" not in os.environ, "create_app no debe tocar el entorno global"

    with app1.app_context():
        execute("INSERT INTO products (code, description, base_unit, sale_price, cost_price, "
                "avg_cost, stock, active, updated_at) "
                "VALUES ('A1','Producto de A','unidad',10,5,5,1,1,'2026-01-01')")
    with app2.app_context():
        execute("INSERT INTO products (code, description, base_unit, sale_price, cost_price, "
                "avg_cost, stock, active, updated_at) "
                "VALUES ('B1','Producto de B','unidad',10,5,5,1,1,'2026-01-01')")
    with app1.app_context():
        codigos = {r["code"] for r in query("SELECT code FROM products")}
    with app2.app_context():
        codigos2 = {r["code"] for r in query("SELECT code FROM products")}
    assert codigos == {"A1"}, codigos
    assert codigos2 == {"B1"}, codigos2


# ================================================== ARQ-03 — leer no escribe
def test_arq03_renderizar_no_modifica_la_base(client, app):
    import sqlite3

    login(client)
    ruta = app.config["FERREGEST_DB"]

    def ultimo_chequeo():
        conn = sqlite3.connect(ruta)
        try:
            return conn.execute("SELECT last_check FROM license_info WHERE id=1").fetchone()[0]
        finally:
            conn.close()

    antes = ultimo_chequeo()
    for _ in range(5):
        for url in ("/", "/pos", "/productos", "/clientes", "/reportes"):
            assert client.get(url).status_code in (200, 403)
    despues = ultimo_chequeo()
    assert antes == despues, (f"ARQ-03: un GET cambió last_check ({antes} -> {despues})")


# ================================================ ARQ-04 — modo demo/producción
def test_arq04_produccion_sin_licencia_bloquea_ventas(tmp_path, monkeypatch):
    from app import create_app
    from app.db import query

    monkeypatch.setenv("FERREGEST_MODE", "production")
    monkeypatch.setenv("FERREGEST_ADMIN_PASSWORD", ADMIN_PW)
    app = create_app(str(tmp_path / "prod.db"))
    app.config["PROPAGATE_EXCEPTIONS"] = False
    cl = app.test_client()

    csrf = login(cl)
    nuevo_producto(cl, csrf, code="P-1", precio=100, stock=10)
    pid = None
    with app.app_context():
        pid = query("SELECT id FROM products WHERE code='P-1'", one=True)["id"]

    r = vender(cl, csrf, pid, 1, 100)
    assert r.status_code == 403, f"en producción sin licencia debe bloquearse: {r.status_code}"
    assert "licencia" in (r.get_json() or {}).get("error", "").lower()

    # Con una licencia válida, la misma instalación vuelve a operar.
    with app.app_context():
        from app import license as lic
        install = lic.get_install_id(create=True)
        payload = {
            "license_id": "LIC-PRUEBA-001", "install_id": install,
            "client": "Ferretería de prueba", "issued_at": "2026-01-01",
            "expires_at": "2030-12-31", "grace_days": 7, "warn_days": 15,
            "status": "activa",
        }
        blob = lic.sign_license(payload)
    r2 = cl.post("/licencias", data={"_csrf": csrf_of(cl), "payload": blob},
                 follow_redirects=False)
    assert r2.status_code == 302, "la licencia válida debe poder importarse"
    csrf = csrf_of(cl)
    assert vender(cl, csrf, pid, 1, 100).status_code == 201


def test_arq04_modo_demo_permite_operar(client):
    csrf = login(client)
    nuevo_producto(client, csrf, code="D-1", precio=50, stock=10)
    from conftest import vender as v
    with client.application.app_context():
        from app.db import query
        pid = query("SELECT id FROM products WHERE code='D-1'", one=True)["id"]
    assert v(client, csrf, pid, 1, 50).status_code == 201
    assert client.get("/").data.decode().find("DEMO") >= 0


# ============================================== ARQ-05 — seed demo protegido
def test_arq05_seed_demo_exige_confirmacion(tmp_path):
    script = os.path.join(BASE, "seed_demo.py")
    db = str(tmp_path / "demo.db")

    # (a) sin confirmación explícita no corre
    p = subprocess.run([os.sys.executable, script], capture_output=True, text=True,
                       env={**os.environ, "FERREGEST_MODE": "demo", "FERREGEST_DB": db})
    assert p.returncode != 0, "sin --confirmar-demo el seed debe negarse"
    assert "SEGURIDAD" in p.stdout
    assert not os.path.exists(db), "no debe crear la base si no hay confirmación"

    # (b) en modo producción tampoco
    p = subprocess.run([os.sys.executable, script, "--confirmar-demo"],
                       capture_output=True, text=True,
                       env={**os.environ, "FERREGEST_MODE": "production",
                            "FERREGEST_DB": str(tmp_path / "demo2.db")})
    assert p.returncode != 0, "en producción el seed debe negarse"

    # (c) no quedan contraseñas fijas en el script
    with open(script, encoding="utf-8") as fh:
        fuente = fh.read()
    for mala in ("admin123", "vendedor123", "deposito123"):
        assert mala not in fuente, f"ARQ-05: sigue la clave fija {mala} en seed_demo.py"


# ============================================ ARQ-08 — límite de intentos real
def test_arq08_bloqueo_de_login_persistente(app, client, db_path):
    from app import create_app
    from app import security

    for intento in range(security.cfg.LOGIN_MAX_ATTEMPTS):
        r = client.post("/login", data={"username": ADMIN_USER, "password": "incorrecta",
                                        "_csrf": csrf_of(client, "/login")})
        assert r.status_code == 401, f"intento {intento + 1}: {r.status_code}"

    r = client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PW,
                                    "_csrf": csrf_of(client, "/login")})
    assert r.status_code == 429, "tras superar el umbral la cuenta debe bloquearse"

    # El contador está en la base: sobrevive a un reinicio (otra instancia).
    otra = create_app(db_path)
    with otra.app_context():
        assert security.login_failures(ADMIN_USER) >= security.cfg.LOGIN_MAX_ATTEMPTS
        assert security.login_locked(ADMIN_USER)
        security.clear_login_failures(ADMIN_USER)
        assert not security.login_locked(ADMIN_USER)


# ======================================================= ARQ-10 — logout POST
def test_arq10_logout_exige_post_y_csrf(client):
    csrf = login(client)
    assert client.get("/").status_code == 200

    assert client.get("/logout").status_code == 405, "el logout por GET ya no existe"
    r = client.post("/logout", data={}, follow_redirects=False)
    assert r.status_code == 400, "sin token CSRF debe rechazarse"
    assert client.get("/").status_code == 200, "la sesión sigue activa"

    r = client.post("/logout", data={"_csrf": csrf}, follow_redirects=False)
    assert r.status_code == 302
    assert client.get("/").status_code == 302, "la sesión debe haberse cerrado"


# ================================================ ARQ-13 — sin redirección abierta
@pytest.mark.parametrize("destino", ["//evil.com/robo", "/\\evil.com", "https://evil.com",
                                     "http:/evil.com"])
def test_arq13_next_no_redirige_fuera_del_sitio(client, destino):
    token = re.search(r'name="_csrf" value="([^"]+)"',
                      client.get("/login").data.decode()).group(1)
    r = client.post("/login?next=" + destino,
                    data={"username": ADMIN_USER, "password": ADMIN_PW, "_csrf": token},
                    follow_redirects=False)
    assert r.status_code == 302
    destino_final = r.headers["Location"]
    assert "evil.com" not in destino_final, f"redirección abierta a {destino_final}"
    assert destino_final.startswith("/"), destino_final


def test_arq13_next_interno_si_funciona(client):
    token = re.search(r'name="_csrf" value="([^"]+)"',
                      client.get("/login").data.decode()).group(1)
    r = client.post("/login?next=/productos",
                    data={"username": ADMIN_USER, "password": ADMIN_PW, "_csrf": token},
                    follow_redirects=False)
    assert r.headers["Location"].endswith("/productos")


# =============================================== ARQ-14/16 — cabeceras y errores
def test_arq14_cabeceras_de_seguridad(client):
    login(client)
    r = client.get("/")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert r.headers.get("Referrer-Policy") == "same-origin"
    assert "default-src 'self'" in r.headers.get("Content-Security-Policy", "")
    assert "no-store" in r.headers.get("Cache-Control", "")


def test_arq16_error_500_no_filtra_el_traceback(tmp_path):
    from app import create_app

    app = create_app(str(tmp_path / "boom.db"))
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/_boom")
    def boom():
        raise RuntimeError("SECRETO-INTERNO-DE-PRUEBA")

    client = app.test_client()
    r = client.get("/_boom")
    assert r.status_code == 500
    cuerpo = r.data.decode()
    assert "SECRETO-INTERNO-DE-PRUEBA" not in cuerpo
    assert "RuntimeError" not in cuerpo
    assert "incidente" in cuerpo


# ==================================================== transversal: CSRF y permisos
def test_csrf_ausente_rechaza_post(client):
    csrf = login(client)
    r = client.post("/productos/nuevo", data={"code": "SIN-CSRF", "description": "x"})
    assert r.status_code == 400
    r = client.post("/productos/nuevo", data={"_csrf": "token-falso", "code": "X"})
    assert r.status_code == 400
    assert csrf  # el token real sí se obtuvo


def test_api_sin_sesion_devuelve_401(client):
    r = client.post("/api/ventas", json={"items": [], "payments": []},
                    headers={"X-CSRF-Token": csrf_of(client, "/login")})
    assert r.status_code == 401
