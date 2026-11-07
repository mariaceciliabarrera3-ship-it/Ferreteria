"""FerreGest AR — utilidades compartidas de las pruebas de auditoría.

Cada prueba crea su propia base SQLite temporal (``tmp_path`` de pytest), así
que ninguna toca la base del comercio ni la de demostración.
"""
import os
import re
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# Clave de firma efímera, sólo para pruebas (jamás en producción ni en GitHub).
os.environ.setdefault("LICENSE_SIGNING_KEY", "clave-de-pruebas-ferregest-2026")

ADMIN_USER, ADMIN_PW = "admin", "admin123"


@pytest.fixture
def db_path(tmp_path):
    """Ruta de una base SQLite nueva y aislada para la prueba."""
    return str(tmp_path / "arq_prueba.db")


@pytest.fixture
def app(db_path):
    """Aplicación Flask nueva, con su propia base (ARQ-02)."""
    from app import create_app

    application = create_app(db_path)
    application.config["TESTING"] = True
    application.config["PROPAGATE_EXCEPTIONS"] = False
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_of(client, page="/"):
    r = client.get(page)
    m = re.search(r'name="csrf-token" content="([^"]+)"', r.data.decode())
    assert m, "no se encontró el token CSRF en la página"
    return m.group(1)


def login(client, username=ADMIN_USER, password=ADMIN_PW):
    r = client.get("/login")
    m = re.search(r'name="_csrf" value="([^"]+)"', r.data.decode())
    assert m, "no se encontró el formulario de login"
    r = client.post("/login", data={"username": username, "password": password,
                                    "_csrf": m.group(1)}, follow_redirects=False)
    assert r.status_code == 302, f"login falló: {r.status_code}"
    return csrf_of(client)


def nuevo_producto(client, csrf, code="TORN-1", description="Tornillo", precio=100.0,
                   stock=50.0, unidad="unidad"):
    """Crea un producto por la UI (validando permisos y CSRF de paso)."""
    r = client.post("/productos/nuevo", data={
        "_csrf": csrf, "code": code, "barcode": "", "description": description,
        "brand": "", "base_unit": unidad, "default_sale_unit": unidad,
        "cost_price": str(precio / 2), "sale_price": str(precio),
        "wholesale_price": str(precio * 0.9), "stock_inicial": str(stock),
        "stock_min": "0", "stock_max": "0", "location": "",
    }, follow_redirects=False)
    assert r.status_code == 302, f"alta de producto falló: {r.status_code}"
    return r


def vender(client, csrf, product_id, qty, precio, descuento=0.0):
    """Registra una venta por la API del POS."""
    return client.post("/api/ventas", json={
        "items": [{"product_id": product_id, "unit": "unidad", "qty": qty,
                   "unit_price": precio, "discount": descuento}],
        "payments": [{"method": "efectivo", "amount": round(qty * precio - descuento, 2)}],
    }, headers={"X-CSRF-Token": csrf})
