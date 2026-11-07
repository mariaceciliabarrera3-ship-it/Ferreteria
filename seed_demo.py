#!/usr/bin/env python3
"""FerreGest AR — datos ficticios de demostración.

Uso:
    FERREGEST_MODE=demo FERREGEST_DB=/ruta/demo.db python3 seed_demo.py --confirmar-demo

Crea una ferretería ficticia completa («Ferretería El Martillo») con productos,
clientes, proveedores, ventas de los últimos días, transferencias, compras,
caja y gastos.

ARQ-05 — candados de seguridad (no se puede ejecutar "por accidente"):
  1. Exige modo demo explícito: ``FERREGEST_MODE=demo`` (o ``--confirmar-demo``
     con ``FERREGEST_SEED_DEMO=1``). Si la instalación está en ``production``,
     el seed se niega a correr.
  2. Exige confirmación explícita: ``--confirmar-demo`` o
     ``FERREGEST_SEED_DEMO=1``.
  3. Se niega a tocar una base que ya tenga movimientos comerciales (ventas,
     compras, clientes o movimientos de stock): eso indica datos reales.
  4. **No contiene contraseñas fijas.** Las toma de
     ``FERREGEST_DEMO_ADMIN_PASSWORD`` / ``_VENDEDOR`` / ``_DEPOSITO``; si no
     están definidas, genera claves aleatorias, las muestra por pantalla y las
     guarda en ``var/claves_demo.txt`` (permisos 0600, fuera del repositorio).
  5. Nunca cambia la contraseña de usuarios existentes salvo que se pida con
     ``--rotar-claves-demo``.

NO usar datos personales ni financieros reales.
"""
import argparse
import os
import random
import secrets
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("FERREGEST_DB", os.path.join(BASE_DIR, "ferregest.db"))

from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def d(days_ago: int, hour=10, minute=0) -> str:
    dt = datetime.now(TZ) - timedelta(days=days_ago)
    return dt.replace(hour=hour, minute=minute, second=0).strftime("%Y-%m-%d %H:%M:%S")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Carga datos ficticios de demostración (sólo en bases demo).")
    ap.add_argument("--confirmar-demo", action="store_true",
                    help="Confirma que la base destino es de demostración.")
    ap.add_argument("--rotar-claves-demo", action="store_true",
                    help="Permite cambiar la clave de usuarios demo existentes.")
    return ap.parse_args(argv)


def modo_es_demo() -> bool:
    return (os.environ.get("FERREGEST_MODE", "") or "").strip().lower() == "demo"


def confirmado(args) -> bool:
    return bool(args.confirmar_demo or os.environ.get("FERREGEST_SEED_DEMO") == "1")


def tiene_datos_comerciales() -> bool:
    """True si la base parece contener datos de un comercio real."""
    from app.db import query

    for tabla in ("sales", "purchases", "customers", "stock_movements",
                  "cash_sessions", "audit_log"):
        try:
            row = query(f"SELECT COUNT(*) AS c FROM {tabla}", one=True)
        except Exception:
            continue
        if row and row["c"]:
            return True
    return False


def claves_demo() -> dict:
    """Contraseñas de demostración: nunca fijas en el código (ARQ-05)."""
    generadas = {}
    claves = {}
    for usuario, var in (("admin", "FERREGEST_DEMO_ADMIN_PASSWORD"),
                         ("vendedor", "FERREGEST_DEMO_VENDOR_PASSWORD"),
                         ("deposito", "FERREGEST_DEMO_STOCK_PASSWORD")):
        valor = (os.environ.get(var, "") or "").strip()
        if valor:
            claves[usuario] = valor
        else:
            valor = secrets.token_urlsafe(12)
            claves[usuario] = valor
            generadas[usuario] = valor
    if generadas:
        print("\nClaves de demostración generadas automáticamente (no están en el código):")
        for u, v in generadas.items():
            print(f"  {u}: {v}")
        _guardar_claves(claves)
        print("Guárdelas ahora: no se pueden volver a mostrar.\n")
    else:
        print("Usando claves de demostración definidas por variables de entorno.")
    return claves


def _guardar_claves(claves: dict):
    try:
        carpeta = os.path.join(BASE_DIR, "var")
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, "claves_demo.txt")
        umask = os.umask(0o077)
        try:
            with open(ruta, "w", encoding="utf-8") as fh:
                for u, v in claves.items():
                    fh.write(f"{u}: {v}\n")
        finally:
            os.umask(umask)
        print(f"Se guardaron en {ruta} (permisos 0600).")
    except OSError:
        print("No se pudo escribir var/claves_demo.txt: anote las claves de arriba.")


def main(argv=None):
    args = parse_args(argv)

    if not modo_es_demo():
        print("SEGURIDAD: este script sólo corre en modo demo.\n"
              "  Exporte FERREGEST_MODE=demo y apunte FERREGEST_DB a una base de\n"
              "  demostración (nunca la base real del comercio).")
        return 2
    if not confirmado(args):
        print("SEGURIDAD: falta la confirmación explícita.\n"
              "  Ejecute:  FERREGEST_MODE=demo python3 seed_demo.py --confirmar-demo\n"
              "  (o exporte FERREGEST_SEED_DEMO=1)")
        return 2

    from app import create_app
    from app import db as dbm
    from app.db import execute, insert, query, round2
    from app.security import hash_password
    from app.services import apply_movement, create_sale

    app = create_app()
    with app.app_context():
        if query("SELECT COUNT(*) AS c FROM products", one=True)["c"] > 0:
            print("Ya hay productos cargados: seed omitido (idempotente).")
            return 0
        if tiene_datos_comerciales():
            print("SEGURIDAD: la base destino ya tiene movimientos comerciales "
                  "(ventas, compras, clientes, caja o auditoría).\n"
                  "  El seed de demostración se detiene para no mezclar ni "
                  "sobreescribir datos reales.\n"
                  "  Use una base vacía y distinta: FERREGEST_DB=/ruta/demo.db")
            return 3

        # ---------- usuarios ----------
        claves = claves_demo()
        ids = {}
        for username, name, role in (
            ("admin", "Valentina Gómez (proprietaria)", "administrador"),
            ("vendedor", "Ramiro Sánchez", "vendedor"),
            ("deposito", "Lucía Fernández", "stock"),
        ):
            pw = claves[username]
            existente = query("SELECT id FROM users WHERE username=?", (username,), one=True)
            if existente:
                ids[username] = existente["id"]
                if args.rotar_claves_demo:
                    execute("UPDATE users SET password_hash=?, full_name=?, role=? WHERE id=?",
                            (hash_password(pw), name, role, existente["id"]))
                else:
                    # Nunca se toca la clave de una instalación existente.
                    execute("UPDATE users SET full_name=?, role=? WHERE id=?",
                            (name, role, existente["id"]))
                continue
            ids[username] = insert(
                "INSERT INTO users (username, password_hash, full_name, role, perms, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (username, hash_password(pw), name, role, "{}", d(30, 8)))
        admin = ids["admin"]
        vend = ids["vendedor"]

        # Contexto de usuario administrador para permisos y auditoría del seed
        from flask import g as _g
        _g.user = query("SELECT * FROM users WHERE id=?", (admin,), one=True)

        # ---------- negocio / config ----------
        for k, v in (
            ("business_name", "Ferretería El Martillo (demo)"),
            ("business_address", "Av. Siempre Viva 742 — Córdoba, Argentina"),
            ("business_cuit", "30-71999888-4"),
            ("business_iva", "Responsable Inscripto (datos ficticios)"),
            ("ticket_footer", "¡Gracias por su compra! — comprobante interno de gestión"),
            ("fiscal_note", "Este comprobante NO es una factura electrónica ante ARCA."),
        ):
            execute("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) "
                    "DO UPDATE SET value=excluded.value", (k, v))

        # ---------- impuesto demo (INACTIVO por defecto) ----------
        execute(
            "INSERT INTO taxes (name, rate, mode, scope, active, notes, created_at) VALUES "
            "(?,?, 'agregado', 'global', 0, ?, ?)",
            ("IVA 21% (demo — desactivado)", 21,
             "Concepto de ejemplo: actívelo en Configuración → Impuestos para verlo "
             "aplicar en ventas nuevas.", d(30)))

        # ---------- cuentas de transferencia ----------
        execute("INSERT INTO transfer_accounts (bank, alias, cbu, holder) VALUES (?,?,?,?)",
                ("Banco Nación", "FERRE.ELMARTILLO",
                 "011000000000000000000000", "Ferretería El Martillo SRL (ficticia)"))
        execute("INSERT INTO transfer_accounts (bank, alias, cbu, holder) VALUES (?,?,?,?)",
                ("Banco Galicia", "MARTILLO.CTA",
                 "015000000000000000000000", "Ferretería El Martillo SRL (ficticia)"))

        # ---------- categorías ----------
        cats = {}
        for name in ("Bulonería y fijaciones", "Herramientas manuales",
                     "Herramientas eléctricas", "Pinturas y accesorios",
                     "Electricidad", "Caños y plomería",
                     "Materiales de construcción", "Jardín"):
            cats[name] = insert("INSERT INTO categories (name) VALUES (?)", (name,))

        # ---------- proveedores ----------
        sup = {}
        for name, cuit, terms in (
            ("Distribuidora El Tornillo SRL", "30-70111222-3", "30 días fecha factura"),
            ("Electricidad del Centro SA", "30-70444555-6", "15 días"),
            ("Pinturas Hermanos Gómez", "27-25666777-8", "Contado"),
            ("Materiales del Sur", "30-70888999-0", "30 días fecha factura"),
        ):
            sup[name] = insert(
                "INSERT INTO suppliers (name, cuit, contact, phone, payment_terms, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (name, cuit, "Comercial: Pedro Vidal", "0800-123-4567 (ficticio)",
                 terms, d(40)))

        # ---------- clientes ----------
        cli = {}
        for name, doc, limit, note in (
            ("Carpintería López", "20-22333444-5", 300000, "Cliente mayorista"),
            ("Obra Los Aromos", "30-555666777-1", 800000, "Cuenta corriente aprobada"),
            ("María Pérez", "27-30999888-2", 0, "Consumidora frecuente"),
            ("Electricista Rodríguez", "20-31111222-9", 150000, "Técnico independiente"),
        ):
            cli[name] = insert(
                "INSERT INTO customers (name, doc, address, phone, credit_limit, notes, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (name, doc, "Calle Ficticia 100, Córdoba", "351-000-0000 (ficticio)",
                 limit, note, d(35)))

        # ---------- unidades extra ----------
        for u in ("balde", "rollo", "metro", "tonelada"):
            execute("INSERT OR IGNORE INTO units (name) VALUES (?)", (u,))

        # ---------- productos ----------
        # (code, desc, marca, cat, base_unit, default_unit, cost, price, stock, min, convs)
        PROD = [
            ("CBL-25", "Cable unipolar 2,5 mm²", "Calkins", "Electricidad",
             "metro", "metro", 1000, 1500, 480, 100, {"rollo": 100}),
            ("TORN-815", "Tornillo madera 8 x 1,5 (vástago)", "Fischer", "Bulonería y fijaciones",
             "unidad", "paquete", 18, 35, 5200, 500, {"paquete": 50, "caja": 100}),
            ("TUER-M8", "Tuerca hexagonal M8 galvanizada", "AB", "Bulonería y fijaciones",
             "unidad", "caja", 12, 25, 8400, 1000, {"caja": 100}),
            ("CLAV-3", "Clavo punta París 3\"", "Serpel", "Bulonería y fijaciones",
             "kilo", "kilo", 1400, 2100, 95, 20, {"caja": 5}),
            ("PINT-L20", "Pintura látex interior blanco 20 L", "Alba", "Pinturas y accesorios",
             "litro", "lata", 65000, 92000, 140, 20, {"lata": 20, "balde": 20}),
            ("PINT-ESM5", "Esmalte sintético alquidico 1 L", "Sinteplast", "Pinturas y accesorios",
             "litro", "litro", 9800, 15500, 60, 10, {}),
            ("ROD-F4", "Rodillo lana 4 pulgadas", "Dyco", "Pinturas y accesorios",
             "unidad", "unidad", 3200, 5900, 40, 8, {}),
            ("CAÑO-PVC25", "Caño PVC 25 mm (barra 3 m)", "Tigre", "Caños y plomería",
             "metro", "barra", 900, 1450, 310, 60, {"barra": 3, "unidad": 3}),
            ("CONE-25", "Conexión en Y PVC 25 mm", "Tigre", "Caños y plomería",
             "unidad", "caja", 380, 700, 420, 50, {"caja": 25}),
            ("GRIFO-12", "Grifería de pileta cromada", "FV", "Caños y plomería",
             "unidad", "unidad", 24500, 38900, 18, 4, {}),
            ("MART-680", "Martillo carpintero 680 g", "Stanley", "Herramientas manuales",
             "unidad", "unidad", 8900, 14900, 22, 5, {}),
            ("LLAVE-ING", "Juego de llaves inglesas 6 pzas", "Bremen", "Herramientas manuales",
             "juego", "juego", 28000, 45900, 12, 3, {}),
            ("PINZA-8", "Pinza universal 8 pulgadas", "Truper", "Herramientas manuales",
             "unidad", "unidad", 7600, 12900, 15, 4, {}),
            ("TAL-750", "Taladro percutor 750 W", "Bosch", "Herramientas eléctricas",
             "unidad", "unidad", 88000, 139900, 6, 2, {}),
            ("DIS-115", "Disco de corte 115 mm para metal (x5)", "Bosch", "Herramientas eléctricas",
             "paquete", "paquete", 9800, 16900, 30, 6, {"caja": 10}),
            ("BETA-M6", "Set de brocas HSS M6 (x10)", "Irwin", "Herramientas eléctricas",
             "juego", "juego", 15400, 24900, 10, 3, {}),
            ("BOMB-LED", "Bombita LED 9 W fría", "Philips", "Electricidad",
             "unidad", "paquete", 2400, 4200, 260, 40, {"paquete": 4, "caja": 20}),
            ("LLAVE-TOMA", "Llave térmica 1x20 mm", "Sica", "Electricidad",
             "unidad", "unidad", 3900, 6800, 70, 12, {}),
            ("CEM-50", "Cemento Portland 50 kg", "Loma Negra", "Materiales de construcción",
             "kilo", "bolsa", 6200, 8900, 40, 10, {"bolsa": 50}),
            ("ARE-05", "Arena fina lavada (m3)", "Minera", "Materiales de construcción",
             "metro", "bolsa", 18000, 26000, 24, 5, {"bolsa": 0.05}),
            ("LADR-8", "Ladrillo hueco 8 canales", "Cerámica", "Materiales de construcción",
             "unidad", "pallet", 420, 690, 3200, 400, {"pallet": 100}),
            ("MANG-12", "Manguera reforzada 12 mm (rollo)", "Flexa", "Jardín",
             "metro", "rollo", 780, 1250, 260, 50, {"rollo": 25}),
            ("TIJ-JARD", "Tijera de podar 20 cm", "Tramontina", "Jardín",
             "unidad", "unidad", 11500, 18900, 9, 3, {}),
            ("ABO-10", "Abono orgánico 10 kg", "Vida", "Jardín",
             "bolsa", "bolsa", 4800, 7900, 35, 8, {}),
            ("CINT-PVC", "Cinta aisladora PVC negra", "3M", "Electricidad",
             "unidad", "paquete", 850, 1600, 340, 50, {"paquete": 10}),
        ]
        prods = {}
        for (code, desc, brand, cat, base, dflt, cost, price, stock, smin,
                convs) in PROD:
            pid = insert(
                "INSERT INTO products (code, description, brand, category_id, base_unit, "
                "default_sale_unit, cost_price, avg_cost, sale_price, wholesale_price, "
                "special_price, stock, stock_min, stock_max, location, updated_at, active) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                (code, desc, brand, cats[cat], base, dflt, cost, cost, price,
                 round2(price * 0.85), round2(price * 0.78), 0, smin,
                 smin * 8, f"Estante {random.choice('ABCDEFGH')}{random.randint(1,9)}",
                 d(20)))
            for unit, factor in convs.items():
                execute("INSERT INTO unit_conversions (product_id, unit, factor) VALUES (?,?,?)",
                        (pid, unit, factor))
            # stock inicial auditable
            apply_movement(pid, stock, "inventario_inicial", admin,
                           "Carga inicial de demo", "seed", None)
            execute("UPDATE products SET stock=? WHERE id=?", (stock, pid))
            execute("INSERT INTO price_history (product_id, field, old_value, new_value, "
                    "user_id, changed_at, note) VALUES (?,?,?,?,?,?,?)",
                    (pid, "sale_price", 0, price, admin, d(20), "Precio inicial demo"))
            prods[code] = pid

        # ---------- compras ----------
        def make_purchase(days, supplier, items, pay="credito"):
            subtotal = 0.0
            number = f"O-{query('SELECT COALESCE(MAX(id),0)+1 AS n FROM purchases', one=True)['n']:06d}"
            purchase_id = insert(
                "INSERT INTO purchases (number, supplier_id, datetime, user_id, status, "
                "pay_method, subtotal, total, notes) VALUES (?,?,?,?,?,?,?,?,?)",
                (number, sup[supplier], d(days, 9), admin, "recibida", pay,
                 0, 0, "Compra de demo"))
            total = 0
            for code, qty, unit, cost in items:
                p = query("SELECT * FROM products WHERE id=?", (prods[code],), one=True)
                line = round2(qty * cost)
                iid = insert(
                    "INSERT INTO purchase_items (purchase_id, product_id, description, unit, "
                    "qty_ordered, qty_received, unit_cost, line_total) VALUES (?,?,?,?,?,?,?,?)",
                    (purchase_id, p["id"], p["description"], unit, qty, 0, cost, line))
                total = round2(total + line)
                # recepción completa
                factor = 1.0
                conv = query("SELECT factor FROM unit_conversions WHERE product_id=? AND lower(unit)=?",
                             (p["id"], unit.lower()), one=True)
                if conv:
                    factor = conv["factor"]
                elif unit.lower() != p["base_unit"].lower():
                    factor = 1.0
                qty_base = round2(qty * factor)
                cost_base = round2(cost / factor)
                old_stock = float(p["stock"])
                new_avg = round2((max(old_stock, 0) * float(p["avg_cost"]) + qty_base * cost_base) /
                                 (max(old_stock, 0) + qty_base)) if old_stock + qty_base > 0 else cost_base
                execute("UPDATE products SET avg_cost=?, cost_price=?, last_purchase_date=?, "
                        "updated_at=? WHERE id=?", (new_avg, cost_base, d(days)[:10],
                                                    d(days), p["id"]))
                apply_movement(p["id"], qty_base, "compra", admin,
                               f"Recepción compra {number}", "purchase", purchase_id)
                execute("UPDATE purchase_items SET qty_received=? WHERE id=?", (qty, iid))
            execute("UPDATE purchases SET subtotal=?, total=? WHERE id=?",
                    (total, total, purchase_id))
            if pay == "credito":
                execute("INSERT INTO supplier_ledger (supplier_id, datetime, type, description, "
                        "debit, credit, ref_type, ref_id) VALUES (?,?,?,?,?,0,'purchase',?)",
                        (sup[supplier], d(days, 9), "compra_credito",
                         f"Compra {number}", total, purchase_id))
            return purchase_id

        make_purchase(12, "Distribuidora El Tornillo SRL",
                      [("TORN-815", 20, "caja", 1700), ("TUER-M8", 10, "caja", 1100)])
        make_purchase(8, "Electricidad del Centro SA",
                      [("CBL-25", 100, "rollo", 95000), ("BOMB-LED", 5, "caja", 8000)])
        make_purchase(3, "Materiales del Sur",
                      [("CEM-50", 10, "bolsa", 6100), ("CLAV-3", 5, "caja", 6800)],
                      pay="transferencia")

        # ---------- ventas de los últimos 14 días ----------
        random.seed(42)
        vendedor = vend
        sale_count = 0
        for days in range(14, 0, -1):
            n_sales = random.randint(1, 3) if days % 7 != 0 else random.randint(0, 1)
            for s in range(n_sales):
                hour = random.randint(9, 18)
                lines = random.sample(PROD, k=random.randint(1, 3))
                items = []
                for pr in lines:
                    code = pr[0]
                    unit = pr[5]  # default sale unit
                    qty = random.choice([1, 1, 2, 3, 0.5, 2.5]) if pr[4] in ("metro", "litro", "kilo") \
                        else random.choice([1, 1, 1, 2, 4])
                    p = query("SELECT * FROM products WHERE id=?", (prods[code],), one=True)
                    if float(p["stock"]) <= 0:
                        continue
                    items.append({"product_id": p["id"], "unit": unit, "qty": qty,
                                  "unit_price": float(p["sale_price"]), "discount": 0})
                if not items:
                    continue
                customer = random.choice([None, None, "María Pérez",
                                          "Electricista Rodríguez", "Carpintería López"])
                customer_id = cli[customer] if customer else None
                # medio de pago
                r = random.random()
                if days <= 3 and r < 0.2:
                    payments = [{"method": "transferencia", "amount": 0, "transfer": {
                        "bank": "Banco Nación", "reference": f"TR{random.randint(100000,999999)}",
                        "informed": True, "notes": "Informada por el cliente"}}]
                    pay_kind = "transfer"
                elif r < 0.15 and customer_id:
                    payments = [{"method": "cuenta_corriente", "amount": 0}]
                    pay_kind = "cc"
                elif r < 0.45:
                    payments = [{"method": "debito", "amount": 0}]
                    pay_kind = "debito"
                else:
                    payments = [{"method": "efectivo", "amount": 0}]
                    pay_kind = "efectivo"
                try:
                    # cotizar para conocer total y poder completar el importe
                    from app.services import quote_sale
                    quote = quote_sale(items)
                    if quote["total"] <= 0:
                        continue
                    payments[0]["amount"] = quote["total"]
                    user = admin if s % 2 == 0 else vendedor
                    # crear venta con fecha retroactiva: se inserta y luego se corrige fecha
                    sale = create_sale(user, customer_id, items, payments,
                                       notes="Venta de demostración")
                    execute("UPDATE sales SET datetime=? WHERE id=?", (d(days, hour,
                            random.randint(0, 59)), sale["id"]))
                    sale_count += 1
                except Exception as e:  # noqa: BLE001
                    import traceback
                    print("  (venta omitida)", type(e).__name__, e)
                    if "list indices" in str(e) or "request context" in str(e):
                        traceback.print_exc()

        # transferencia VERIFICADA de ejemplo
        pend = query("SELECT * FROM transfers WHERE status='informada' ORDER BY id LIMIT 1",
                     one=True)
        if pend:
            execute("UPDATE transfers SET status='verificada', verified_by=?, verified_at=?, "
                    "verify_note=? WHERE id=?", (admin, d(1, 16),
                    "Verificada en el extracto del banco (demo)", pend["id"]))
            execute("UPDATE sales SET payment_status='pagada' WHERE id=?", (pend["sale_id"],))

        # ---------- cobros y cuenta corriente ----------
        cobro_cli = cli["Carpintería López"]
        execute("INSERT INTO customer_payments (customer_id, datetime, amount, method, user_id, notes) "
                "VALUES (?,?,?,?,?,?)", (cobro_cli, d(5, 11), 50000, "efectivo", admin,
                                         "Cobro parcial (demo)"))
        execute("INSERT INTO customer_ledger (customer_id, datetime, type, description, "
                "debit, credit, ref_type) VALUES (?,?,'cobro','Cobro parcial (demo)',0,?,'payment')",
                (cobro_cli, d(5, 11), 50000))

        # ---------- caja ----------
        for days_back in (6, 5, 4, 3, 2, 1):
            sid = insert(
                "INSERT INTO cash_sessions (opened_at, user_open, initial, closed_at, "
                "user_close, counted, expected, diff, status) VALUES (?,?,?,?,?,?,?,?, 'cerrada')",
                (d(days_back, 8, 30), admin, 20000, d(days_back, 20, 0), admin,
                 0, 0, 0))
            # ingresos del día: ventas en efectivo registradas ese día
            dia = d(days_back, 12)[:10]
            for v in query(
                    "SELECT s.number, SUM(p.amount) AS m FROM sales s "
                    "JOIN payments p ON p.sale_id=s.id "
                    "WHERE p.method='efectivo' AND s.status='activa' "
                    "AND substr(s.datetime,1,10)=? GROUP BY s.id", (dia,)):
                execute("INSERT INTO cash_movements (session_id, datetime, type, concept, "
                        "amount, user_id, ref_type, ref_id) VALUES (?,?,?,?,?,?,'sale',NULL)",
                        (sid, f"{dia} 12:00:00", "ingreso", f"Venta {v['number']}",
                         round2(v["m"]), admin))
            # gasto de ejemplo
            if days_back == 4:
                eid = insert("INSERT INTO expenses (datetime, concept, category, amount, method, "
                             "user_id, from_cash) VALUES (?,?,?,?,?,?,1)",
                             (d(days_back, 12), "Electricidad del mes (ficticio)", "Servicios",
                              18500, "efectivo", admin))
                execute("INSERT INTO cash_movements (session_id, datetime, type, concept, amount, "
                        "user_id, ref_type, ref_id) VALUES (?,?,?,?,?,?, 'expense', ?)",
                        (sid, d(days_back, 12), "egreso", "Gasto: Electricidad del mes",
                         18500, admin, eid))
            net = query("SELECT COALESCE(SUM(CASE WHEN type='ingreso' THEN amount ELSE -amount END),0) AS n "
                        "FROM cash_movements WHERE session_id=?", (sid,), one=True)["n"]
            expected = round2(20000 + net)
            execute("UPDATE cash_sessions SET expected=?, counted=?, diff=? WHERE id=?",
                    (expected, expected, 0, sid))

        # sesión de caja ABIERTA hoy
        today_sid = insert(
            "INSERT INTO cash_sessions (opened_at, user_open, initial, status) VALUES (?,?,?, 'abierta')",
            (d(0, 8, 30), admin, 20000))

        # ---------- devolución de ejemplo (con caja abierta) ----------
        sale_dev = query(
            "SELECT s.id, si.id AS item_id, si.qty FROM sales s "
            "JOIN sale_items si ON si.sale_id=s.id JOIN products p ON p.id=si.product_id "
            "WHERE s.status='activa' AND si.qty > 1 ORDER BY s.id DESC LIMIT 1", one=True)
        if sale_dev:
            from app.services import create_return
            try:
                create_return(sale_dev["id"],
                              [{"sale_item_id": sale_dev["item_id"], "qty": 1}],
                              admin, "Cliente se llevó de más (demo)", "efectivo")
            except Exception as e:  # noqa: BLE001
                print(f"  (devolución omitida: {e})")

        # ventas de HOY para el panel (sin fecha retroactiva)
        for i in range(3):
            code = random.choice(list(prods.keys()))
            p = query("SELECT * FROM products WHERE id=?", (prods[code],), one=True)
            unit = p["default_sale_unit"]
            qty = 2.5 if p["base_unit"] in ("metro", "litro", "kilo") else 1
            if float(p["stock"]) < qty:
                continue
            method = "efectivo" if i % 2 == 0 else "transferencia"
            payments = [{"method": method, "amount": 0}]
            if method == "transferencia":
                payments[0]["transfer"] = {"bank": "Banco Galicia",
                                           "reference": f"TRHOY{i}00",
                                           "informed": True, "notes": ""}
            from app.services import quote_sale
            q = quote_sale([{"product_id": p["id"], "unit": unit, "qty": qty,
                             "unit_price": float(p["sale_price"]), "discount": 0}])
            payments[0]["amount"] = q["total"]
            try:
                create_sale(admin, None,
                            [{"product_id": p["id"], "unit": unit, "qty": qty,
                              "unit_price": float(p["sale_price"]), "discount": 0}],
                            payments, notes="Venta de hoy (demo)")
            except Exception as e:  # noqa: BLE001
                print(f"  (venta hoy omitida: {e})")

        # La instalación queda marcada como demo (aviso permanente en la UI).
        execute("INSERT INTO settings (key, value) VALUES ('demo_mode','1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        print("\n✅ Seed de demostración completado.")
        print("   Usuarios demo: admin · vendedor · deposito")
        print("   Las claves son las que se definieron por variable de entorno o las")
        print("   generadas automáticamente (ver var/claves_demo.txt).")
        print(f"   Productos: {len(prods)} · Ventas creadas: {sale_count}")
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
