"""Compras, recepción de mercadería, proveedores y pagos a proveedores."""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from .db import execute, insert, now_date, now_iso, query, round2
from .security import audit, can, login_required, permission_required
from .services import (create_purchase, pay_supplier, receive_purchase,
                       supplier_balance)

bp = Blueprint("purchases", __name__)


def _uid():
    from .security import current_user

    return current_user()["id"]


# ------------------------------------------------------------- COMPRAS

@bp.route("/compras")
@login_required
def lista():
    if not (can("compras.gestionar") or can("compras.consultar")):
        abort(403)
    fdesde = request.args.get("desde") or now_date()[:7] + "-01"
    fhasta = request.args.get("hasta") or now_date()
    rows = query(
        "SELECT p.*, s.name AS supplier_name FROM purchases p "
        "LEFT JOIN suppliers s ON s.id=p.supplier_id "
        "WHERE substr(p.datetime,1,10) BETWEEN ? AND ? ORDER BY p.id DESC LIMIT 200",
        (fdesde, fhasta))
    totales = query(
        "SELECT COALESCE(SUM(total),0) AS t, COUNT(*) AS c FROM purchases "
        "WHERE substr(datetime,1,10) BETWEEN ? AND ?", (fdesde, fhasta), one=True)
    return render_template("compras.html", compras=rows, desde=fdesde, hasta=fhasta,
                           totales=totales)


@bp.route("/compras/nueva", methods=["GET", "POST"])
@login_required
@permission_required("compras.gestionar")
def nueva():
    if request.method == "POST":
        data = request.get_json(silent=True)
        if data:
            purchase = create_purchase(_uid(), data.get("supplier_id"),
                                       data.get("items") or [],
                                       data.get("pay_method") or "credito",
                                       data.get("notes") or "")
            return {"ok": True, "id": purchase["id"], "number": purchase["number"],
                    "total": purchase["total"]}, 201
        flash("Use el formulario interactivo de compras.", "error")
    suppliers = query("SELECT id, name FROM suppliers WHERE active=1 ORDER BY name")
    products = query(
        "SELECT id, code, description, base_unit, avg_cost, cost_price FROM products "
        "WHERE active=1 ORDER BY description LIMIT 600")
    units = query("SELECT name FROM units ORDER BY name")
    return render_template("compra_form.html", suppliers=suppliers, products=products,
                           units=[u["name"] for u in units])


@bp.route("/compras/<int:pid>")
@login_required
def detalle(pid):
    if not (can("compras.gestionar") or can("compras.consultar")):
        abort(403)
    purchase = query(
        "SELECT p.*, s.name AS supplier_name, s.id AS sup_id FROM purchases p "
        "LEFT JOIN suppliers s ON s.id=p.supplier_id WHERE p.id=?", (pid,), one=True)
    if purchase is None:
        abort(404)
    items = query("SELECT * FROM purchase_items WHERE purchase_id=?", (pid,))
    receipts = query(
        "SELECT r.*, u.username FROM purchase_receipts r "
        "LEFT JOIN users u ON u.id=r.user_id WHERE r.purchase_id=? ORDER BY r.id DESC", (pid,))
    receipt_items = {}
    if receipts:
        ids = ",".join("?" * len(receipts))
        for ri in query(f"SELECT * FROM receipt_items WHERE receipt_id IN ({ids})",
                        [r["id"] for r in receipts]):
            receipt_items.setdefault(ri["receipt_id"], []).append(ri)
    can_receive = can("compras.gestionar") and purchase["status"] != "recibida"
    return render_template("compra_detalle.html", purchase=purchase, items=items,
                           receipts=receipts, receipt_items=receipt_items,
                           can_receive=can_receive)


@bp.route("/compras/<int:pid>/recibir", methods=["POST"])
@login_required
@permission_required("compras.gestionar")
def recibir(pid):
    data = request.get_json(silent=True) or {}
    lines = data.get("lines") or []
    if not lines:
        # soporte de formulario tradicional
        lines = []
        for k, v in request.form.items():
            if k.startswith("qty_") and v:
                lines.append({"purchase_item_id": int(k.split("_")[1]), "qty": v})
    purchase = receive_purchase(pid, lines, _uid(), data.get("notes") or request.form.get("notes") or "")
    if request.is_json:
        return {"ok": True, "status": purchase["status"]}, 200
    flash(f"Recepción registrada. Estado: {purchase['status']}.", "ok")
    return redirect(url_for("purchases.detalle", pid=pid))


# ---------------------------------------------------------- PROVEEDORES

@bp.route("/proveedores")
@login_required
def proveedores():
    if not (can("compras.gestionar") or can("compras.consultar") or can("productos.gestionar")):
        abort(403)
    q = (request.args.get("q") or "").strip()
    sql = "SELECT * FROM suppliers WHERE active=1"
    args = []
    if q:
        sql += " AND (name LIKE ? OR cuit LIKE ?)"
        args = [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY name LIMIT 200"
    rows = query(sql, args)
    saldos = {r["supplier_id"]: r["s"] for r in query(
        "SELECT supplier_id, COALESCE(SUM(debit-credit),0) AS s FROM supplier_ledger "
        "GROUP BY supplier_id")}
    return render_template("proveedores.html", proveedores=rows, q=q, saldos=saldos)


@bp.route("/proveedores/nuevo", methods=["GET", "POST"])
@login_required
@permission_required("compras.gestionar")
def proveedor_nuevo():
    if request.method == "POST":
        f = request.form
        name = (f.get("name") or "").strip()
        if not name:
            flash("El nombre es obligatorio.", "error")
            return redirect(url_for("purchases.proveedor_nuevo"))
        sid = insert(
            "INSERT INTO suppliers (name, cuit, contact, address, phone, email, payment_terms, notes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (name, f.get("cuit", "").strip(), f.get("contact", "").strip(),
             f.get("address", "").strip(), f.get("phone", "").strip(),
             f.get("email", "").strip(), f.get("payment_terms", "").strip(),
             f.get("notes", "").strip(), now_iso()),
        )
        audit("crear", "proveedor", sid, {"name": name})
        flash("Proveedor dado de alta.", "ok")
        return redirect(url_for("purchases.proveedor_detalle", sid=sid))
    return render_template("proveedor_form.html", s=None)


@bp.route("/proveedores/<int:sid>", methods=["GET", "POST"])
@login_required
def proveedor_detalle(sid):
    if not (can("compras.gestionar") or can("compras.consultar")):
        abort(403)
    s = query("SELECT * FROM suppliers WHERE id=?", (sid,), one=True)
    if s is None:
        abort(404)
    if request.method == "POST":
        if not can("compras.gestionar"):
            abort(403)
        f = request.form
        if f.get("action") == "pago":
            try:
                pay_supplier(sid, f.get("amount"), f.get("method") or "transferencia",
                            _uid(), f.get("notes") or "")
                flash("Pago a proveedor registrado.", "ok")
            except Exception as e:  # noqa: BLE001
                flash(str(getattr(e, "description", e)), "error")
            return redirect(url_for("purchases.proveedor_detalle", sid=sid))
        execute(
            "UPDATE suppliers SET name=?, cuit=?, contact=?, address=?, phone=?, email=?, "
            "payment_terms=?, notes=? WHERE id=?",
            ((f.get("name") or s["name"]).strip(), f.get("cuit", s["cuit"]),
             f.get("contact", s["contact"]), f.get("address", s["address"]),
             f.get("phone", s["phone"]), f.get("email", s["email"]),
             f.get("payment_terms", s["payment_terms"]), f.get("notes", s["notes"]), sid))
        audit("modificar", "proveedor", sid, {})
        flash("Proveedor actualizado.", "ok")
        return redirect(url_for("purchases.proveedor_detalle", sid=sid))

    compras = query(
        "SELECT * FROM purchases WHERE supplier_id=? ORDER BY id DESC LIMIT 50", (sid,))
    movs = query(
        "SELECT * FROM supplier_ledger WHERE supplier_id=? ORDER BY id DESC LIMIT 50", (sid,))
    pagos = query(
        "SELECT * FROM supplier_payments WHERE supplier_id=? ORDER BY id DESC LIMIT 50", (sid,))
    productos = query(
        "SELECT id, code, description, cost_price, last_purchase_date FROM products "
        "WHERE supplier_id=? AND active=1 ORDER BY description", (sid,))
    return render_template("proveedor_detalle.html", s=s, compras=compras, movs=movs,
                           pagos=pagos, productos=productos,
                           saldo=supplier_balance(sid))
