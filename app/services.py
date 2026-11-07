"""FerreGest AR — servicios de negocio (transaccionales).

Toda escritura relevante ocurre aquí, dentro de transacciones, de modo que
stock, movimientos, pagos, caja y cuentas corrientes queden siempre coherentes.
Ninguna pantalla modifica existencias sin generar un movimiento auditable.
"""
import json
from datetime import date
from decimal import Decimal

from flask import abort, g

from . import fiscal, license as lic
from .db import (begin, begin_immediate, commit, current_db_path, execute, insert,
                 now_date, now_iso, query, rollback, round2, round4)
from .money import D, EPS, f2, f4, money_str, q2, q4, sum_q2
from .security import audit, can, current_user

# Tolerancia para comparar dinero: medio centavo (Decimal, ver app/money.py).
# EPS se importa desde .money (ARQ-09).


# ---------------------------------------------------------------- utilidades

def unit_factor(product, unit: str) -> float:
    """Cantidad de unidades base que representa 1 'unit' para este producto."""
    unit = (unit or product["base_unit"]).strip().lower()
    if unit == product["base_unit"].strip().lower():
        return 1.0
    row = query(
        "SELECT factor FROM unit_conversions WHERE product_id = ? AND lower(unit) = ?",
        (product["id"], unit), one=True,
    )
    if row is None:
        abort(400, description=f"El producto no admite la unidad '{unit}'.")
    return float(row["factor"])


def sale_units_for(product) -> list[dict]:
    """Unidades en las que se puede vender el producto (base + conversiones)."""
    out = [{"unit": product["base_unit"], "factor": 1.0, "is_base": True}]
    for r in query(
        "SELECT unit, factor FROM unit_conversions WHERE product_id = ? ORDER BY unit",
        (product["id"],),
    ):
        out.append({"unit": r["unit"], "factor": float(r["factor"]), "is_base": False})
    return out


def apply_movement(product_id, qty_delta, mtype, user_id, reason="",
                   ref_type="", ref_id=None, allow_negative=False, commit=False):
    """Actualiza el stock de un producto generando su movimiento auditable."""
    p = query("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    if p is None:
        abort(404, description="Producto inexistente.")
    new_stock = q4(D(p["stock"]) + D(qty_delta))
    if new_stock < -EPS and not allow_negative:
        abort(409, description=(
            f"Stock insuficiente para '{p['description']}': hay {p['stock']} "
            f"{p['base_unit']} y se requieren {abs(float(qty_delta))} "
            f"{p['base_unit']} de salida."
        ))
    execute("UPDATE products SET stock = ?, updated_at = ? WHERE id = ?",
            (float(new_stock), now_iso(), product_id))
    mid = execute(
        "INSERT INTO stock_movements (product_id, datetime, type, qty, stock_after, user_id, reason, ref_type, ref_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (product_id, now_iso(), mtype, float(q4(qty_delta)), float(new_stock), user_id,
         reason, ref_type, ref_id),
    )
    if commit:
        g.db.commit()
    return new_stock, mid


def next_number(table: str, prefix: str, width: int = 6) -> str:
    n = query(f"SELECT COALESCE(MAX(id), 0) + 1 AS n FROM {table}", one=True)["n"]
    return f"{prefix}-{n:0{width}d}"


def customer_balance(customer_id) -> float:
    r = query(
        "SELECT COALESCE(SUM(debit - credit), 0) AS s FROM customer_ledger WHERE customer_id = ?",
        (customer_id,), one=True)
    return float(q2(r["s"]))


def supplier_balance(supplier_id) -> float:
    r = query(
        "SELECT COALESCE(SUM(debit - credit), 0) AS s FROM supplier_ledger WHERE supplier_id = ?",
        (supplier_id,), one=True)
    return float(q2(r["s"]))


def open_cash_session():
    return query("SELECT * FROM cash_sessions WHERE status = 'abierta' ORDER BY id DESC", one=True)


def assert_ops_allowed():
    st = lic.load_state()
    if not st["ops_allowed"]:
        abort(403, description=st["message"])


def recompute_sale_payment_status(sale_id):
    """Estado de cobro: cuenta corriente > transferencia sin verificar > pagada."""
    sale = query("SELECT * FROM sales WHERE id = ?", (sale_id,), one=True)
    if sale is None:
        return
    pays = query("SELECT * FROM payments WHERE sale_id = ?", (sale_id,))
    status = "pagada"
    for p in pays:
        if p["method"] == "cuenta_corriente":
            status = "cuenta_corriente"
            break
        if p["method"] == "transferencia" and p["transfer_id"]:
            tr = query("SELECT status FROM transfers WHERE id = ?", (p["transfer_id"],), one=True)
            if tr and tr["status"] != "verificada":
                status = "pendiente_transferencia"
    if sale["payment_status"] != status:
        execute("UPDATE sales SET payment_status = ? WHERE id = ?", (status, sale_id))


# -------------------------------------------------------------------- VENTAS

def create_sale(user_id, customer_id, items, payments, notes="", allow_negative=False):
    """Registra una venta completa. items/payments llegan del POS (JSON).

    - Recalcula precios e impuestos en el servidor (nunca confía en el cliente).
    - Admite cantidades fraccionadas y unidades convertidas.
    - Transferencias quedan en estado pendiente/informada: NUNCA verificadas.
    """
    assert_ops_allowed()
    u = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    perms_ok_neg = can("stock.negativo")
    if allow_negative and not perms_ok_neg:
        abort(403, description="No tiene permiso para dejar stock negativo.")
    if not items:
        abort(400, description="La venta no tiene renglones.")
    if customer_id:
        cust = query("SELECT id FROM customers WHERE id = ? AND active = 1", (customer_id,), one=True)
        if cust is None:
            abort(400, description="Cliente inexistente o inactivo.")
    else:
        customer_id = None

    begin_immediate()
    try:
        number = next_number("sales", "V")
        sale_id = insert(
            "INSERT INTO sales (number, datetime, user_id, customer_id, status, payment_status, notes) "
            "VALUES (?, ?, ?, ?, 'activa', 'pendiente', ?)",
            (number, now_iso(), user_id, customer_id, notes or ""),
        )

        # ARQ-09: acumuladores en Decimal; sólo se convierten a float al persistir.
        subtotal = discount_total = tax_total = total = cost_total = Decimal("0")
        computed_items = []
        for it in items:
            p = query("SELECT * FROM products WHERE id = ? AND active = 1",
                      (it.get("product_id"),), one=True)
            if p is None:
                abort(400, description="Producto inválido en la venta.")
            try:
                qty = q4(it.get("qty"))
                price = q2(it.get("unit_price"))
                line_disc = q2(it.get("discount") or 0)
            except (TypeError, ValueError, ArithmeticError):
                abort(400, description="Cantidades o precios inválidos.")
            if qty <= 0:
                abort(400, description="La cantidad debe ser mayor que cero.")
            if price < 0 or line_disc < 0:
                abort(400, description="Precios y descuentos no pueden ser negativos.")
            if line_disc > price * qty + EPS:
                abort(400, description="El descuento supera el importe del renglón.")
            if line_disc > 0 and not can("descuentos.aplicar"):
                abort(403, description="No tiene permiso para aplicar descuentos.")
            unit = (it.get("unit") or p["base_unit"]).strip()
            factor = unit_factor(p, unit)
            if unit.lower() != p["base_unit"].lower():
                up = query("SELECT unit FROM unit_conversions WHERE product_id = ? AND lower(unit) = ?",
                           (p["id"], unit.lower()), one=True)
                if up is None:
                    abort(400, description=f"Unidad no habilitada para {p['description']}.")
            qty_base = q4(qty * D(factor))
            taxes = fiscal.applicable_taxes(p, when=now_date())
            calc = fiscal.compute_line_taxes(price, qty, line_disc, taxes)
            line_total = q2(D(calc["base"]) + D(calc["tax_amount"]))
            cost_unit_base = D(p["avg_cost"])
            line_cost = q2(qty_base * cost_unit_base)
            computed_items.append({
                "p": p, "unit": unit, "qty": qty, "price": price, "disc": line_disc,
                "calc": calc, "line_total": line_total, "qty_base": qty_base,
                "line_cost": line_cost,
            })
            subtotal = q2(subtotal + price * qty)
            discount_total = q2(discount_total + line_disc)
            tax_total = q2(tax_total + D(calc["tax_amount"]))
            total = q2(total + line_total)
            cost_total = q2(cost_total + line_cost)

        # Pagos: la suma debe coincidir con el total
        if not payments:
            abort(400, description="Debe indicar al menos un medio de pago.")
        pay_sum = Decimal("0")
        norm_payments = []
        for pay in payments:
            try:
                amount = q2(pay.get("amount"))
            except (TypeError, ValueError, ArithmeticError):
                abort(400, description="Importe de pago inválido.")
            method = pay.get("method")
            if method not in ("efectivo", "transferencia", "debito", "credito", "cuenta_corriente"):
                abort(400, description="Medio de pago no reconocido.")
            if amount <= 0:
                abort(400, description="El importe del pago debe ser mayor que cero.")
            pay_sum = q2(pay_sum + amount)
            norm_payments.append({"method": method, "amount": amount, "raw": pay})
        if abs(pay_sum - total) > Decimal("0.01"):
            abort(400, description=(
                f"La suma de los pagos (${pay_sum}) no coincide con el total (${total})."
            ))

        if any(p["method"] == "cuenta_corriente" for p in norm_payments):
            if customer_id is None:
                abort(400, description="La venta a cuenta corriente requiere un cliente.")
            cust = query("SELECT * FROM customers WHERE id = ?", (customer_id,), one=True)
            if D(cust["credit_limit"]) > 0:
                saldo = D(customer_balance(customer_id))
                if saldo + total > D(cust["credit_limit"]) + EPS:
                    if not can("configuracion.gestionar"):
                        abort(409, description=(
                            f"El cliente supera su límite de crédito (${cust['credit_limit']}). "
                            "Solo un administrador puede autorizarlo."
                        ))

        # 1) Renglones + descuento de stock
        for ci in computed_items:
            allow_neg_line = allow_negative
            new_stock, _mid = apply_movement(
                ci["p"]["id"], -ci["qty_base"], "venta", user_id,
                f"Venta {number}", "sale", sale_id, allow_negative=allow_neg_line,
            )
            insert(
                "INSERT INTO sale_items (sale_id, product_id, description, unit, qty, unit_price, "
                "discount, line_subtotal, tax_breakdown, tax_amount, line_total, cost_snapshot, stock_delta) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (sale_id, ci["p"]["id"], ci["p"]["description"], ci["unit"], float(ci["qty"]),
                 float(ci["price"]), float(ci["disc"]),
                 float(q2(ci["price"] * ci["qty"] - ci["disc"])),
                 json.dumps(ci["calc"]["breakdown"], ensure_ascii=False),
                 float(ci["calc"]["tax_amount"]), float(ci["line_total"]), ci["p"]["avg_cost"],
                 -float(ci["qty_base"])),
            )

        # 2) Pagos (transferencias pendientes)
        for np in norm_payments:
            transfer_id = None
            if np["method"] == "transferencia":
                raw = np["raw"].get("transfer") or {}
                acct = query(
                    "SELECT COALESCE(bank,'') AS bank, COALESCE(alias,'') AS alias, COALESCE(cbu,'') AS cbu "
                    "FROM transfer_accounts WHERE active = 1 ORDER BY id LIMIT 1", one=True)
                default_dest = (f"{acct['bank']} Alias: {acct['alias']} CBU: {acct['cbu']}" if acct else "")
                informed = bool(raw.get("informed"))
                transfer_id = insert(
                    "INSERT INTO transfers (sale_id, customer_id, bank, destination, amount, reference, "
                    "status, informed_at, notes, created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (sale_id, customer_id, raw.get("bank", ""), raw.get("destination") or default_dest,
                     float(np["amount"]), raw.get("reference", ""),
                     "informada" if informed else "pendiente",
                     now_iso() if informed else None,
                     raw.get("notes", ""), now_iso(), user_id),
                )
            insert(
                "INSERT INTO payments (sale_id, method, amount, transfer_id, created_at, user_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sale_id, np["method"], float(np["amount"]), transfer_id, now_iso(), user_id),
            )

        # 3) Totales de la cabecera
        execute(
            "UPDATE sales SET subtotal=?, discount=?, tax_total=?, total=?, cost_total=? WHERE id=?",
            (float(subtotal), float(discount_total), float(tax_total), float(total),
             float(cost_total), sale_id),
        )

        # 4) Caja: el efectivo entra a la sesión abierta (si la hay)
        session = open_cash_session()
        efectivo = sum_q2(p["amount"] for p in norm_payments if p["method"] == "efectivo")
        if efectivo > 0 and session:
            execute(
                "INSERT INTO cash_movements (session_id, datetime, type, concept, amount, user_id, ref_type, ref_id) "
                "VALUES (?, ?, 'ingreso', ?, ?, ?, 'sale', ?)",
                (session["id"], now_iso(), f"Venta {number}", float(efectivo), user_id, sale_id),
            )

        # 5) Cuenta corriente del cliente
        cc = sum_q2(p["amount"] for p in norm_payments if p["method"] == "cuenta_corriente")
        if cc > 0:
            execute(
                "INSERT INTO customer_ledger (customer_id, datetime, type, description, debit, credit, ref_type, ref_id) "
                "VALUES (?, ?, 'venta_credito', ?, ?, 0, 'sale', ?)",
                (customer_id, now_iso(), f"Venta {number} a cuenta corriente", float(cc), sale_id),
            )

        recompute_sale_payment_status(sale_id)
        audit("crear", "venta", sale_id, {
            "number": number, "total": float(total), "items": len(computed_items),
            "payments": [p["method"] for p in norm_payments],
        })
        commit()
        return query("SELECT * FROM sales WHERE id = ?", (sale_id,), one=True)
    except Exception:
        rollback()
        raise


def void_sale(sale_id, reason, user_id):
    assert_ops_allowed()
    if not can("ventas.anular"):
        abort(403, description="No tiene permiso para anular ventas.")
    if not reason or not reason.strip():
        abort(400, description="Debe indicar el motivo de anulación.")
    sale = query("SELECT * FROM sales WHERE id = ?", (sale_id,), one=True)
    if sale is None:
        abort(404, description="Venta inexistente.")
    if sale["status"] != "activa":
        abort(400, description="La venta ya fue anulada.")
    begin_immediate()
    try:
        for it in query("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)):
            apply_movement(it["product_id"], -it["stock_delta"], "anulacion", user_id,
                           f"Anulación {sale['number']}: {reason}", "sale", sale_id,
                           allow_negative=True)
        # Revertir efectivo en caja (se registra el egreso compensador)
        session = open_cash_session()
        efectivo = query(
            "SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE sale_id = ? AND method = 'efectivo'",
            (sale_id,), one=True)["s"]
        if efectivo and session:
            execute(
                "INSERT INTO cash_movements (session_id, datetime, type, concept, amount, user_id, ref_type, ref_id) "
                "VALUES (?, ?, 'egreso', ?, ?, ?, 'sale_void', ?)",
                (session["id"], now_iso(), f"Anulación venta {sale['number']}",
                 float(q2(efectivo)), user_id, sale_id),
            )
        # Revertir cuenta corriente
        execute(
            "INSERT INTO customer_ledger (customer_id, datetime, type, description, debit, credit, ref_type, ref_id) "
            "SELECT customer_id, ?, 'anulacion', ?, 0, (SELECT COALESCE(SUM(amount),0) FROM payments "
            " WHERE sale_id = ? AND method = 'cuenta_corriente'), 'sale', ? "
            "FROM sales WHERE id = ? AND customer_id IS NOT NULL",
            (now_iso(), f"Anulación venta {sale['number']}", sale_id, sale_id, sale_id),
        )
        # Transferencias asociadas quedan documentadas como anuladas
        execute("UPDATE transfers SET status = 'rechazada', verify_note = COALESCE(NULLIF(verify_note,''), '') || "
                " CASE WHEN status IN ('pendiente','informada') THEN ' [venta anulada]' ELSE '' END "
                "WHERE sale_id = ?", (sale_id,))
        execute(
            "UPDATE sales SET status='anulada', void_reason=?, voided_by=?, voided_at=? WHERE id=?",
            (reason, user_id, now_iso(), sale_id),
        )
        audit("anular", "venta", sale_id, {"number": sale["number"], "reason": reason})
        commit()
    except Exception:
        rollback()
        raise
    return query("SELECT * FROM sales WHERE id = ?", (sale_id,), one=True)


def create_return(sale_id, lines, user_id, reason, refund_method="efectivo"):
    """Devolución (nota de crédito interna) de renglones de una venta."""
    assert_ops_allowed()
    if not can("ventas.anular"):
        abort(403, description="No tiene permiso para registrar devoluciones.")
    sale = query("SELECT * FROM sales WHERE id = ?", (sale_id,), one=True)
    if sale is None or sale["status"] != "activa":
        abort(400, description="Solo se puede devolver una venta activa.")
    if refund_method not in ("efectivo", "cuenta_corriente", "transferencia"):
        abort(400, description="Medio de devolución inválido.")
    if refund_method == "cuenta_corriente" and not sale["customer_id"]:
        abort(400, description="La venta no tiene cliente para acreditar en cuenta corriente.")
    begin_immediate()
    try:
        ret_id = insert(
            "INSERT INTO sale_returns (sale_id, number, datetime, user_id, refund_method, reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sale_id, next_number("sale_returns", "NC"), now_iso(), user_id,
             refund_method, reason or ""),
        )
        total = tax_total = Decimal("0")
        for ln in lines:
            item = query("SELECT * FROM sale_items WHERE id = ? AND sale_id = ?",
                         (ln.get("sale_item_id"), sale_id), one=True)
            if item is None:
                abort(400, description="Renglón de venta inválido.")
            already = query(
                "SELECT COALESCE(SUM(sri.qty),0) AS q FROM sale_return_items sri "
                "JOIN sale_returns r ON r.id = sri.return_id "
                "WHERE r.sale_id = ? AND sri.sale_item_id = ?",
                (sale_id, item["id"]), one=True)["q"]
            try:
                qty = q4(ln.get("qty"))
            except (TypeError, ValueError, ArithmeticError):
                abort(400, description="Cantidad de devolución inválida.")
            if qty <= 0 or qty > D(item["qty"]) - D(already) + EPS:
                abort(400, description="Cantidad a devolver inválida (supera lo vendido).")
            unit_tax = (D(item["tax_amount"]) / D(item["qty"])) if item["qty"] else Decimal("0")
            unit_disc_price = (D(item["line_subtotal"]) / D(item["qty"])) if item["qty"] else Decimal("0")
            line_total = q2(unit_disc_price * qty + unit_tax * qty)
            line_tax = q2(unit_tax * qty)
            p = query("SELECT * FROM products WHERE id = ?", (item["product_id"],), one=True)
            factor = unit_factor(p, item["unit"])
            qty_base = q4(qty * D(factor))
            apply_movement(item["product_id"], qty_base, "devolucion", user_id,
                           f"Devolución {sale['number']}", "return", ret_id)
            insert(
                "INSERT INTO sale_return_items (return_id, sale_item_id, product_id, qty, unit_price, "
                "tax_amount, line_total, stock_delta) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ret_id, item["id"], item["product_id"], float(qty), float(unit_disc_price),
                 float(line_tax), float(line_total), float(qty_base)),
            )
            total = q2(total + line_total)
            tax_total = q2(tax_total + line_tax)

        cash_movement_id = None
        ledger_id = None
        efectivo = query(
            "SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE sale_id = ? AND method='efectivo'",
            (sale_id,), one=True)["s"]
        cc_paid = query(
            "SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE sale_id = ? AND method='cuenta_corriente'",
            (sale_id,), one=True)["s"]
        if refund_method == "efectivo":
            session = open_cash_session()
            if efectivo > 0:
                target = session or query(
                    "SELECT * FROM cash_sessions ORDER BY id DESC LIMIT 1", one=True)
                if target:
                    cur = execute(
                        "INSERT INTO cash_movements (session_id, datetime, type, concept, amount, user_id, ref_type, ref_id) "
                        "VALUES (?, ?, 'egreso', ?, ?, ?, 'return', ?)",
                        (target["id"], now_iso(), f"Devolución {sale['number']}",
                         float(total), user_id, ret_id),
                    )
                    cash_movement_id = cur
        elif refund_method == "cuenta_corriente":
            cur = execute(
                "INSERT INTO customer_ledger (customer_id, datetime, type, description, debit, credit, ref_type, ref_id) "
                "VALUES (?, ?, 'devolucion', ?, 0, ?, 'return', ?)",
                (sale["customer_id"], now_iso(),
                 f"Devolución {sale['number']}", float(total), ret_id),
            )
            ledger_id = cur

        execute("UPDATE sale_returns SET total=?, tax_total=?, cash_movement_id=?, ledger_id=? WHERE id=?",
                (float(total), float(tax_total), cash_movement_id, ledger_id, ret_id))
        audit("devolver", "venta", sale_id, {"return": ret_id, "total": float(total),
                                             "method": refund_method, "reason": reason})
        commit()
        return query("SELECT * FROM sale_returns WHERE id = ?", (ret_id,), one=True)
    except Exception:
        rollback()
        raise


# ------------------------------------------------------------------- COMPRAS

def create_purchase(user_id, supplier_id, items, pay_method, notes=""):
    assert_ops_allowed()
    if not can("compras.gestionar"):
        abort(403, description="No tiene permiso para registrar compras.")
    if pay_method not in ("efectivo", "transferencia", "credito"):
        abort(400, description="Condición de pago inválida.")
    if not items:
        abort(400, description="La compra no tiene renglones.")
    supplier = None
    if supplier_id:
        supplier = query("SELECT * FROM suppliers WHERE id = ? AND active = 1",
                         (supplier_id,), one=True)
        if supplier is None:
            abort(400, description="Proveedor inexistente.")
    if pay_method == "credito" and supplier is None:
        abort(400, description="La compra a crédito requiere proveedor.")
    begin_immediate()
    try:
        number = next_number("purchases", "O")
        purchase_id = insert(
            "INSERT INTO purchases (number, supplier_id, datetime, user_id, status, pay_method, notes) "
            "VALUES (?, ?, ?, ?, 'pendiente', ?, ?)",
            (number, supplier_id, now_iso(), user_id, pay_method, notes or ""),
        )
        subtotal = tax_total = total = Decimal("0")
        for it in items:
            p = query("SELECT * FROM products WHERE id = ? AND active = 1",
                      (it.get("product_id"),), one=True)
            if p is None:
                abort(400, description="Producto inválido en la compra.")
            try:
                qty = q4(it.get("qty") or 0)
                cost = q2(it.get("unit_cost") or 0)
            except (TypeError, ValueError, ArithmeticError):
                abort(400, description="Cantidad o costo inválido.")
            if qty <= 0 or cost < 0:
                abort(400, description="Cantidad o costo inválido.")
            unit = (it.get("unit") or p["base_unit"]).strip()
            unit_factor(p, unit)  # valida unidad
            taxes = fiscal.applicable_taxes(p, when=now_date())
            calc = fiscal.compute_line_taxes(cost, qty, 0, taxes)
            line_total = q2(D(calc["base"]) + D(calc["tax_amount"]))
            insert(
                "INSERT INTO purchase_items (purchase_id, product_id, description, unit, qty_ordered, "
                "unit_cost, line_total) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (purchase_id, p["id"], p["description"], unit, float(qty), float(cost),
                 float(line_total)),
            )
            subtotal = q2(subtotal + D(calc["base"]))
            tax_total = q2(tax_total + D(calc["tax_amount"]))
            total = q2(total + line_total)
        execute("UPDATE purchases SET subtotal=?, tax_total=?, total=? WHERE id=?",
                (float(subtotal), float(tax_total), float(total), purchase_id))
        if pay_method == "credito":
            execute(
                "INSERT INTO supplier_ledger (supplier_id, datetime, type, description, debit, credit, ref_type, ref_id) "
                "VALUES (?, ?, 'compra_credito', ?, ?, 0, 'purchase', ?)",
                (supplier_id, now_iso(), f"Compra {number}", float(total), purchase_id),
            )
        audit("crear", "compra", purchase_id, {"number": number, "total": float(total),
                                               "supplier": supplier["name"] if supplier else "—"})
        commit()
        return query("SELECT * FROM purchases WHERE id = ?", (purchase_id,), one=True)
    except Exception:
        rollback()
        raise


def receive_purchase(purchase_id, receipts, user_id, notes=""):
    """receipts: [{'purchase_item_id': id, 'qty': n}, ...] — recepción parcial total."""
    assert_ops_allowed()
    if not can("compras.gestionar"):
        abort(403, description="No tiene permiso para recibir mercadería.")
    purchase = query("SELECT * FROM purchases WHERE id = ?", (purchase_id,), one=True)
    if purchase is None:
        abort(404, description="Orden de compra inexistente.")
    begin_immediate()
    try:
        receipt_id = insert(
            "INSERT INTO purchase_receipts (purchase_id, datetime, user_id, notes) VALUES (?, ?, ?, ?)",
            (purchase_id, now_iso(), user_id, notes or ""),
        )
        received_any = False
        for r in receipts:
            item = query("SELECT * FROM purchase_items WHERE id = ? AND purchase_id = ?",
                         (r.get("purchase_item_id"), purchase_id), one=True)
            if item is None:
                abort(400, description="Renglón de compra inválido.")
            qty = q4(r.get("qty") or 0)
            if qty <= 0:
                continue
            if D(item["qty_received"]) + qty > D(item["qty_ordered"]) + EPS:
                abort(409, description=(
                    f"'{item['description']}': se recibiría más de lo pedido "
                    f"({item['qty_received']} + {qty} > {item['qty_ordered']})."))
            p = query("SELECT * FROM products WHERE id = ?", (item["product_id"],), one=True)
            factor = D(unit_factor(p, item["unit"]))
            qty_base = q4(qty * factor)
            cost_base = q2(D(item["unit_cost"]) / factor) if factor else Decimal("0")

            # Ponderado para no perder el costo histórico
            old_stock = D(p["stock"])
            old_avg = D(p["avg_cost"])
            if old_stock + qty_base > 0:
                base_for_avg = max(old_stock, Decimal("0"))
                new_avg = q2((base_for_avg * old_avg + qty_base * cost_base) /
                             (base_for_avg + qty_base)) if (base_for_avg + qty_base) else cost_base
            else:
                new_avg = cost_base
            execute("UPDATE products SET avg_cost=?, cost_price=?, last_purchase_date=?, updated_at=? WHERE id=?",
                    (float(new_avg), float(cost_base), now_date(), now_iso(), p["id"]))
            fiscal.price_history_save(p["id"], "cost_price", p["cost_price"], float(cost_base), user_id,
                                      f"Compra {purchase['number']}")
            apply_movement(p["id"], qty_base, "compra", user_id,
                           f"Recepción compra {purchase['number']}", "purchase", purchase_id)
            # avg_cost se escribe después del movimiento para conservar el precio anterior en price_history
            execute("UPDATE purchase_items SET qty_received = qty_received + ? WHERE id = ?",
                    (float(qty), item["id"]))
            insert("INSERT INTO receipt_items (receipt_id, purchase_item_id, qty) VALUES (?, ?, ?)",
                   (receipt_id, item["id"], float(qty)))
            received_any = True

        if received_any:
            pending = query(
                "SELECT COUNT(*) AS c FROM purchase_items WHERE purchase_id = ? AND qty_received < qty_ordered",
                (purchase_id,), one=True)["c"]
            status = "recibida" if pending == 0 else "parcial"
            execute("UPDATE purchases SET status=?, received_at=? WHERE id=?",
                    (status, now_iso(), purchase_id))
            audit("recibir", "compra", purchase_id, {"receipt": receipt_id, "status": status})
        commit()
        return query("SELECT * FROM purchases WHERE id = ?", (purchase_id,), one=True)
    except Exception:
        rollback()
        raise


def pay_supplier(supplier_id, amount, method, user_id, notes=""):
    if not can("compras.gestionar"):
        abort(403, description="No tiene permiso para pagar proveedores.")
    amount = q2(amount)
    if amount <= 0:
        abort(400, description="El importe debe ser mayor que cero.")
    saldo = D(supplier_balance(supplier_id))
    if amount > saldo + EPS and not can("configuracion.gestionar"):
        abort(409, description=f"El pago supera la deuda (${saldo}). Solo un administrador puede autorizarlo.")
    begin_immediate()
    try:
        pid = execute(
            "INSERT INTO supplier_payments (supplier_id, datetime, amount, method, user_id, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (supplier_id, now_iso(), float(amount), method, user_id, notes or ""),
        )
        execute(
            "INSERT INTO supplier_ledger (supplier_id, datetime, type, description, debit, credit, ref_type, ref_id) "
            "VALUES (?, ?, 'pago', ?, 0, ?, 'payment', ?)",
            (supplier_id, now_iso(), f"Pago a proveedor ({method})", float(amount), pid),
        )
        if method == "efectivo":
            session = open_cash_session()
            if session:
                execute(
                    "INSERT INTO cash_movements (session_id, datetime, type, concept, amount, user_id, ref_type, ref_id) "
                    "VALUES (?, ?, 'egreso', ?, ?, ?, 'supplier_payment', ?)",
                    (session["id"], now_iso(), f"Pago a proveedor #{supplier_id}", float(amount),
                     user_id, pid),
                )
        audit("pago", "proveedor", supplier_id, {"amount": float(amount), "method": method})
        commit()
        return pid
    except Exception:
        rollback()
        raise


# --------------------------------------------------------------------- CAJA

def cash_open(user_id, initial):
    assert_ops_allowed()
    if not can("caja.operar"):
        abort(403, description="No tiene permiso para abrir caja.")
    if open_cash_session():
        abort(400, description="Ya hay una sesión de caja abierta.")
    initial = q2(initial)
    if initial < 0:
        abort(400, description="El saldo inicial no puede ser negativo.")
    sid = execute(
        "INSERT INTO cash_sessions (opened_at, user_open, initial, status) VALUES (?, ?, ?, 'abierta')",
        (now_iso(), user_id, float(initial)),
    )
    audit("abrir", "caja", sid, {"initial": float(initial)})
    return sid


def cash_movement(session_id, mtype, concept, amount, user_id):
    assert_ops_allowed()
    if not can("caja.operar"):
        abort(403, description="No tiene permiso para mover caja.")
    session = query("SELECT * FROM cash_sessions WHERE id = ?", (session_id,), one=True)
    if session is None or session["status"] != "abierta":
        abort(400, description="La sesión de caja no está abierta.")
    if mtype not in ("ingreso", "egreso"):
        abort(400, description="Tipo de movimiento inválido.")
    amount = q2(amount)
    if amount <= 0:
        abort(400, description="El importe debe ser mayor que cero.")
    if not concept.strip():
        abort(400, description="Debe indicar un concepto.")
    mid = execute(
        "INSERT INTO cash_movements (session_id, datetime, type, concept, amount, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, now_iso(), mtype, concept.strip(), float(amount), user_id),
    )
    audit("movimiento_caja", "caja", session_id,
          {"type": mtype, "amount": float(amount), "concept": concept})
    return mid


def cash_expected(session) -> float:
    r = query(
        "SELECT COALESCE(SUM(CASE WHEN type='ingreso' THEN amount ELSE -amount END),0) AS d "
        "FROM cash_movements WHERE session_id = ?", (session["id"],), one=True)
    return float(q2(D(session["initial"]) + D(r["d"])))


def cash_close(user_id, counted, notes=""):
    assert_ops_allowed()
    if not can("caja.cerrar"):
        abort(403, description="No tiene permiso para cerrar caja.")
    session = open_cash_session()
    if session is None:
        abort(400, description="No hay sesión de caja abierta.")
    counted = q2(counted)
    expected = q2(cash_expected(session))
    diff = q2(counted - expected)
    execute(
        "UPDATE cash_sessions SET closed_at=?, user_close=?, counted=?, expected=?, diff=?, "
        "status='cerrada', notes=? WHERE id=?",
        (now_iso(), user_id, float(counted), float(expected), float(diff),
         notes or "", session["id"]),
    )
    audit("cerrar", "caja", session["id"],
          {"expected": float(expected), "counted": float(counted), "diff": float(diff)})
    return session["id"], expected, diff


# ------------------------------------------------------- CLIENTES / COBROS

def customer_payment(customer_id, amount, method, user_id, notes=""):
    if not can("cuentas.consultar"):
        abort(403, description="No tiene permiso para registrar cobros.")
    amount = q2(amount)
    if amount <= 0:
        abort(400, description="El importe debe ser mayor que cero.")
    if method not in ("efectivo", "debito", "credito", "transferencia"):
        abort(400, description="Medio de cobro inválido.")
    begin_immediate()
    try:
        if method == "transferencia":
            # Solo se acredita cuando un administrador verifique la transferencia.
            tid = execute(
                "INSERT INTO transfers (customer_id, destination, amount, status, created_at, created_by, notes) "
                "VALUES (?, '', ?, 'pendiente', ?, ?, ?)",
                (customer_id, float(amount), now_iso(), user_id,
                 f"Cobro en espera de verificación. {notes}"),
            )
            audit("cobro_pendiente", "cliente", customer_id,
                  {"amount": float(amount), "transfer_id": tid})
            commit()
            return {"pending_transfer": tid}
        pid = execute(
            "INSERT INTO customer_payments (customer_id, datetime, amount, method, user_id, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (customer_id, now_iso(), float(amount), method, user_id, notes or ""),
        )
        execute(
            "INSERT INTO customer_ledger (customer_id, datetime, type, description, debit, credit, ref_type, ref_id) "
            "VALUES (?, ?, 'cobro', ?, 0, ?, 'payment', ?)",
            (customer_id, now_iso(), f"Cobro ({method})", float(amount), pid),
        )
        if method == "efectivo":
            session = open_cash_session()
            if session:
                execute(
                    "INSERT INTO cash_movements (session_id, datetime, type, concept, amount, user_id, ref_type, ref_id) "
                    "VALUES (?, ?, 'ingreso', ?, ?, ?, 'customer_payment', ?)",
                    (session["id"], now_iso(), f"Cobro cliente #{customer_id}", float(amount),
                     user_id, pid),
                )
        audit("cobrar", "cliente", customer_id,
              {"amount": float(amount), "method": method})
        commit()
        return {"payment_id": pid}
    except Exception:
        rollback()
        raise


def verify_transfer(transfer_id, decision, user_id, note=""):
    """Verificación manual de una transferencia (nunca automática)."""
    if not can("transferencias.verificar"):
        abort(403, description="No tiene permiso para verificar transferencias.")
    if decision not in ("verificada", "rechazada"):
        abort(400, description="Decisión inválida.")
    tr = query("SELECT * FROM transfers WHERE id = ?", (transfer_id,), one=True)
    if tr is None:
        abort(404, description="Transferencia inexistente.")
    if tr["status"] in ("verificada", "rechazada"):
        abort(400, description="La transferencia ya fue resuelta.")
    begin_immediate()
    try:
        execute(
            "UPDATE transfers SET status=?, verified_by=?, verified_at=?, verify_note=? WHERE id=?",
            (decision, user_id, now_iso(), note or "", transfer_id),
        )
        if decision == "verificada":
            if tr["sale_id"]:
                recompute_sale_payment_status(tr["sale_id"])
            elif tr["customer_id"]:
                # Cobro a cuenta corriente: se acredita recién ahora
                pid = execute(
                    "INSERT INTO customer_payments (customer_id, datetime, amount, method, user_id, notes) "
                    "VALUES (?, ?, ?, 'transferencia', ?, ?)",
                    (tr["customer_id"], now_iso(), tr["amount"], user_id,
                     f"Transferencia #{transfer_id} verificada. {note}"),
                )
                execute(
                    "INSERT INTO customer_ledger (customer_id, datetime, type, description, debit, credit, ref_type, ref_id) "
                    "VALUES (?, ?, 'cobro', ?, 0, ?, 'payment', ?)",
                    (tr["customer_id"], now_iso(),
                     f"Cobro por transferencia #{transfer_id} (verificada)", tr["amount"], pid),
                )
        audit("transferencia_" + decision, "transferencia", transfer_id,
              {"sale_id": tr["sale_id"], "amount": float(tr["amount"]), "note": note})
        commit()
        return query("SELECT * FROM transfers WHERE id = ?", (transfer_id,), one=True)
    except Exception:
        rollback()
        raise


def mark_transfer_informed(transfer_id, user_id):
    tr = query("SELECT * FROM transfers WHERE id = ?", (transfer_id,), one=True)
    if tr is None:
        abort(404, description="Transferencia inexistente.")
    if tr["status"] != "pendiente":
        abort(400, description="La transferencia ya tiene estado.")
    execute("UPDATE transfers SET status='informada', informed_at=? WHERE id=?",
            (now_iso(), transfer_id))
    audit("transferencia_informada", "transferencia", transfer_id, {})
    return tr


def backup_json() -> str:
    """Exportación completa de datos (JSON) — disponible aunque esté suspendida."""
    import sqlite3

    conn = sqlite3.connect(current_db_path())
    conn.row_factory = sqlite3.Row
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    out = {"fecha": now_iso(), "tabla": {}, "tables": tables}
    for t in tables:
        out["tabla"][t] = [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
    conn.close()
    return json.dumps(out, ensure_ascii=False, default=str, indent=1)


def quote_sale(items) -> dict:
    """Cotización de una venta SIN registrarla: mismos cálculos que create_sale.

    Centraliza el cálculo de precios/impuestos para que el POS muestre los
    mismos importes que finalmente se persistirán.
    """
    subtotal = discount_total = tax_total = total = cost_total = Decimal("0")
    tax_lines: dict[str, Decimal] = {}
    lines = []
    for it in items or []:
        p = query("SELECT * FROM products WHERE id = ? AND active = 1",
                  (it.get("product_id"),), one=True)
        if p is None:
            abort(400, description="Producto inválido en la cotización.")
        try:
            qty = q4(it.get("qty"))
            price = q2(it.get("unit_price"))
            line_disc = q2(it.get("discount") or 0)
        except (TypeError, ValueError, ArithmeticError):
            abort(400, description="Cantidades o precios inválidos.")
        if qty <= 0:
            continue
        unit = (it.get("unit") or p["base_unit"]).strip()
        factor = D(unit_factor(p, unit))
        qty_base = q4(qty * factor)
        taxes = fiscal.applicable_taxes(p, when=now_date())
        calc = fiscal.compute_line_taxes(price, qty, line_disc, taxes)
        line_total = q2(D(calc["base"]) + D(calc["tax_amount"]))
        for b in calc["breakdown"]:
            key = f"{b['name']} {b['rate']}%"
            if b["mode"] == "incluido":
                key += " (incluido)"
            tax_lines[key] = q2(tax_lines.get(key, Decimal("0")) + D(b["amount"]))
        subtotal = q2(subtotal + price * qty)
        discount_total = q2(discount_total + line_disc)
        tax_total = q2(tax_total + D(calc["tax_amount"]))
        total = q2(total + line_total)
        cost_total = q2(cost_total + qty_base * D(p["avg_cost"]))
        lines.append({
            "product_id": p["id"], "description": p["description"], "unit": unit,
            "qty": float(qty), "unit_price": float(price), "discount": float(line_disc),
            "line_total": float(line_total), "qty_base": float(qty_base),
            "stock_after": float(q2(D(p["stock"]) - qty_base)),
        })
    return {
        "subtotal": float(subtotal), "discount": float(discount_total),
        "tax": float(tax_total), "total": float(total), "cost_total": float(cost_total),
        "tax_lines": [f"{k}: {money_local(v)}" for k, v in tax_lines.items()],
        "lines": lines,
    }


def money_local(v) -> str:
    """Importe en formato argentino (redondeo decimal, ARQ-09)."""
    return money_str(v)
