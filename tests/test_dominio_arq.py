"""FerreGest AR — pruebas de dominio de la auditoría (ARQ-06, 07, 09, 11, 12).

Ejecutar:  python3 -m pytest tests/test_dominio_arq.py -v
"""
import os
import subprocess
import threading
from decimal import Decimal

import pytest

from conftest import BASE, csrf_of, login, nuevo_producto, vender


# ================================================= ARQ-09 — dinero en Decimal
def test_arq09_redondeo_comercial():
    from app import db as dbm
    from app.money import D, q2, sum_q2

    assert q2(Decimal("2.675")) == Decimal("2.68"), "0,005 debe redondear hacia arriba"
    assert q2("2.675") == Decimal("2.68")
    assert q2(0.125) == Decimal("0.13")
    assert dbm.round2(2.675) == 2.68
    # 1000 sumas de un centavo: en float acumulado daba 9,9999999999998…
    assert sum_q2([Decimal("0.01")] * 1000) == Decimal("10.00")
    # Formato argentino de entrada
    assert D("1.234,56") == Decimal("1234.56")
    assert D("1234.56") == Decimal("1234.56")
    assert D(None) == Decimal("0")
    assert D("basura") == Decimal("0")


def test_arq09_impuestos_agregado_e_incluido():
    from app import fiscal

    agregado = [{"name": "IVA 21%", "rate": 21.0, "mode": "agregado"}]
    calc = fiscal.compute_line_taxes(1500, 2.5, 0, agregado)
    assert calc["base"] == 3750.0
    assert calc["tax_amount"] == 787.50

    incluido = [{"name": "IVA 21%", "rate": 21.0, "mode": "incluido"}]
    calc = fiscal.compute_line_taxes(121, 1, 0, incluido)
    assert calc["tax_amount"] == 0.0
    assert calc["included"] == 21.00
    assert calc["base"] == 121.00

    # Descuento antes de impuestos
    calc = fiscal.compute_line_taxes(100, 3, 50, agregado)
    assert calc["base"] == 250.0
    assert calc["tax_amount"] == 52.50


def test_arq09_venta_sin_deriva_de_centavos(client):
    from app.db import query

    csrf = login(client)
    nuevo_producto(client, csrf, code="CENT-1", description="Tornillo 1¢",
                   precio=0.01, stock=1000)
    with client.application.app_context():
        pid = query("SELECT id FROM products WHERE code='CENT-1'", one=True)["id"]

    for _ in range(100):
        r = vender(client, csrf, pid, 1, 0.01)
        assert r.status_code == 201, r.data[:200]

    with client.application.app_context():
        total = query("SELECT COALESCE(SUM(total),0) AS t FROM sales WHERE status='activa'",
                      one=True)["t"]
        stock = query("SELECT stock FROM products WHERE id=?", (pid,), one=True)["stock"]
    assert round(total, 2) == 1.00, f"100 ventas de $0,01 deben sumar $1,00 (fue {total!r})"
    assert round(stock, 4) == 900.0, stock


def test_arq09_renglon_con_fracciones_y_descuento(client):
    from app.db import query

    csrf = login(client)
    nuevo_producto(client, csrf, code="FRAC-1", description="Cable por metro",
                   precio=33.33, stock=100, unidad="metro")
    with client.application.app_context():
        pid = query("SELECT id FROM products WHERE code='FRAC-1'", one=True)["id"]

    r = client.post("/api/ventas", json={
        "items": [{"product_id": pid, "unit": "metro", "qty": 2.5,
                   "unit_price": 33.33, "discount": 0.33}],
        "payments": [{"method": "efectivo", "amount": 83.0}],
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201, r.data[:300]
    sale = r.get_json()
    assert abs(sale["total"] - 83.0) < 0.005, sale
    with client.application.app_context():
        fila = query("SELECT stock FROM products WHERE id=?", (pid,), one=True)
    assert abs(float(fila["stock"]) - 97.5) < 0.0001, fila["stock"]


def test_arq09_caja_suma_sin_error_acumulado(app):
    from app import services
    from app.db import query
    from flask import g

    with app.app_context():
        g.user = query("SELECT * FROM users WHERE id = 1", one=True)
        sid = services.cash_open(1, 0)
        for _ in range(100):
            services.cash_movement(sid, "ingreso", "Venta ínfima", 0.10, 1)
        esperado = services.cash_expected(query("SELECT * FROM cash_sessions WHERE id=?",
                                                (sid,), one=True))
    assert esperado == 10.00, f"100 ingresos de $0,10 deben dar $10,00 (fue {esperado!r})"


# ============================================ ARQ-11 — migraciones atómicas
def test_arq11_migracion_fallida_no_deja_esquema_a_medias(app, db_path):
    from app import db as dbm
    from app.db import query

    mala = os.path.join(BASE, "migrations", "999_prueba_falla.sql")
    with open(mala, "w", encoding="utf-8") as fh:
        fh.write("CREATE TABLE tabla_de_prueba_arq11 (id INTEGER);\n")
        fh.write("ESTO_NO_ES_SQL_VALIDO();\n")
    try:
        with pytest.raises(RuntimeError) as exc:
            dbm.migrate(db_path)
        assert "revirtió" in str(exc.value)
        with app.app_context():
            existe = query("SELECT 1 AS ok FROM sqlite_master WHERE type='table' "
                           "AND name='tabla_de_prueba_arq11'", one=True)
            registrada = query("SELECT 1 AS ok FROM schema_migrations "
                               "WHERE name='999_prueba_falla.sql'", one=True)
        assert existe is None, "la migración fallida dejó una tabla creada"
        assert registrada is None, "la migración fallida quedó marcada como aplicada"
    finally:
        os.remove(mala)

    # La base sigue usable y la migración pendiente desapareció del plan.
    assert dbm.migrate(db_path) == []
    with app.app_context():
        assert query("SELECT COUNT(*) AS c FROM products", one=True)["c"] == 0


def test_arq11_migraciones_registradas_e_idempotentes(app, db_path):
    from app import db as dbm

    aplicadas = dbm.applied_migrations(db_path)
    assert "001_init.sql" in aplicadas
    assert "002_seguridad_login.sql" in aplicadas
    assert dbm.migrate(db_path) == [], "volver a migrar no debe aplicar nada"
    assert dbm.applied_migrations(db_path) == aplicadas


# ================================================ ARQ-12 — SQLite concurrente
def test_arq12_pragma_de_espera_configurado(app):
    from app import config as cfg
    from app.db import get_db

    with app.app_context():
        db = get_db()
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == cfg.BUSY_TIMEOUT_MS
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_arq12_ventas_simultaneas_no_pierden_stock(client):
    from app import services
    from app.db import query

    csrf = login(client)
    nuevo_producto(client, csrf, code="CONC-1", description="Producto concurrente",
                   precio=10, stock=500)
    app = client.application
    with app.app_context():
        pid = query("SELECT id FROM products WHERE code='CONC-1'", one=True)["id"]
        admin = query("SELECT id FROM users WHERE username='admin'", one=True)["id"]

    errores = []
    hilos = 8
    por_hilo = 5

    def vender_uno():
        try:
            with app.app_context():
                for _ in range(por_hilo):
                    services.create_sale(
                        admin, None,
                        [{"product_id": pid, "unit": "unidad", "qty": 1,
                          "unit_price": 10, "discount": 0}],
                        [{"method": "efectivo", "amount": 10}])
        except Exception as exc:  # noqa: BLE001
            errores.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=vender_uno) for _ in range(hilos)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    assert not errores, f"escrituras simultáneas con error: {errores}"
    with app.app_context():
        stock = query("SELECT stock FROM products WHERE id=?", (pid,), one=True)["stock"]
        vendidas = query("SELECT COUNT(*) AS c FROM sales WHERE status='activa'", one=True)["c"]
        movimientos = query("SELECT COALESCE(SUM(qty),0) AS s FROM stock_movements "
                            "WHERE product_id=? AND type='venta'", (pid,), one=True)["s"]
    assert vendidas == hilos * por_hilo, vendidas
    assert abs(float(stock) - (500 - hilos * por_hilo)) < 1e-6, stock
    assert abs(float(movimientos) + hilos * por_hilo) < 1e-6, movimientos


# ==================================== ARQ-06/ARQ-07 — entorno y repositorio
def test_arq06_dependencias_de_prueba_documentadas():
    req = os.path.join(BASE, "requirements.txt")
    dev = os.path.join(BASE, "requirements-dev.txt")
    with open(req, encoding="utf-8") as fh:
        ejecucion = fh.read()
    with open(dev, encoding="utf-8") as fh:
        desarrollo = fh.read()
    assert "pytest" not in ejecucion, "pytest es de desarrollo, no de ejecución"
    assert "-r requirements.txt" in desarrollo
    assert "pytest" in desarrollo


def test_arq07_el_repositorio_no_contiene_secretos_ni_bases():
    proc = subprocess.run(["python3", os.path.join(BASE, "tools", "check_repo.py")],
                          capture_output=True, text=True, cwd=BASE)
    assert proc.returncode == 0, f"check_repo encontró archivos prohibidos:\n{proc.stdout}"


def test_arq07_gitignore_cubre_bases_y_secretos():
    with open(os.path.join(BASE, ".gitignore"), encoding="utf-8") as fh:
        reglas = fh.read()
    for esperado in ("*.db", ".secret", ".env", ".license_key", "*.db-wal",
                     "__pycache__/", "licencias_emitidas.jsonl", "var/"):
        assert esperado in reglas, f"falta {esperado} en .gitignore"
    assert "!.env.example" in reglas


def test_arq07_plantilla_de_variables_sin_valores_reales():
    ejemplo = os.path.join(BASE, ".env.example")
    assert os.path.exists(ejemplo)
    with open(ejemplo, encoding="utf-8") as fh:
        texto = fh.read()
    assert "LICENSE_SIGNING_KEY" in texto
    # Ninguna clave real: los valores quedan vacíos.
    for linea in texto.splitlines():
        if linea.startswith("LICENSE_SIGNING_KEY="):
            assert linea.split("=", 1)[1].strip() in ("", "#"), linea
