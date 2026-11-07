"""Punto de venta, historial de ventas, devoluciones y transferencias."""
import json

from flask import (Blueprint, abort, jsonify, redirect, render_template, request,
                   url_for)

from . import license as lic
from .db import execute, now_date, now_iso, query, round2
from .security import audit, can, login_required, permission_required
from .services import (assert_ops_allowed, create_return, create_sale,
                       open_cash_session, sale_units_for, unit_factor,
                       verify_transfer, void_sale)

bp = Blueprint("pos", __name__)


# ------------------------------------------------------------------- POS UI

@bp.route("/pos")
@login_required
@permission_required("pos.operar")
def pos():
    if not lic.load_state()["ops_allowed"]:
        lic_state = lic.load_state()
        return render_template("error.html", code=403, message=lic_state["message"]), 403
    customers = query("SELECT id, name, doc FROM customers WHERE active=1 ORDER BY name")
    return render_template("pos.html", customers=customers,
                           caja=open_cash_session(),
                           transfer_accounts=query(
                               "SELECT * FROM transfer_accounts WHERE active=1 ORDER BY bank"))


@bp.route("/api/productos")
@login_required
def api_productos():
    """Buscador del POS: por código de barras exacto o texto parcial."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    like = f"%{q}%"
    rows = query(
        "SELECT p.*, c.name AS category_name FROM products p "
        "LEFT JOIN categories c ON c.id=p.category_id "
        "WHERE p.active=1 AND (p.code = ? OR p.barcode = ?) "
        "UNION "
        "SELECT p.*, c.name AS category_name FROM products p "
        "LEFT JOIN categories c ON c.id=p.category_id "
        "WHERE p.active=1 AND (p.description LIKE ? OR p.brand LIKE ?) "
        "ORDER BY description LIMIT 12",
        (q, q, like, like))
    out = []
    for r in rows:
        d = dict(r)
        d["units"] = sale_units_for(r)
        out.append(d)
    return jsonify(out)


@bp.route("/api/ventas", methods=["POST"])
@login_required
@permission_required("pos.operar")
def api_crear_venta():
    data = request.get_json(silent=True) or {}
    from .security import current_user

    u = current_user()
    sale = create_sale(
        user_id=u["id"],
        customer_id=data.get("customer_id"),
        items=data.get("items") or [],
        payments=data.get("payments") or [],
        notes=data.get("notes") or "",
        allow_negative=bool(data.get("allow_negative")),
    )
    return jsonify({"ok": True, "id": sale["id"], "number": sale["number"],
                    "total": sale["total"]}), 201


# ------------------------------------------------------------ HISTORIAL

@bp.route("/ventas")
@login_required
def ventas():
    if not (can("pos.operar") or can("compras.consultar") or can("ventas.anular")):
        abort(403)
    fdesde = request.args.get("desde") or now_date()[:7] + "-01"
    fhasta = request.args.get("hasta") or now_date()
    estado = request.args.get("estado") or ""
    q = (request.args.get("q") or "").strip()
    sql = ("SELECT s.*, u.username, c.name AS customer_name FROM sales s "
           "JOIN users u ON u.id=s.user_id LEFT JOIN customers c ON c.id=s.customer_id "
           "WHERE substr(s.datetime,1,10) BETWEEN ? AND ?")
    args = [fdesde, fhasta]
    if estado in ("activa", "anulada"):
        sql += " AND s.status=?"
        args.append(estado)
    if q:
        sql += " AND (s.number LIKE ? OR c.name LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY s.id DESC LIMIT 300"
    rows = query(sql, args)
    totales = query(
        "SELECT COALESCE(SUM(total),0) AS t, COUNT(*) AS c FROM sales "
        "WHERE status='activa' AND substr(datetime,1,10) BETWEEN ? AND ?",
        (fdesde, fhasta), one=True)
    return render_template("ventas.html", ventas=rows, desde=fdesde, hasta=fhasta,
                           estado=estado, q=q, totales=totales)


def _venta_context(sale_id):
    sale = query(
        "SELECT s.*, u.username, c.name AS customer_name, c.doc AS customer_doc "
        "FROM sales s JOIN users u ON u.id=s.user_id "
        "LEFT JOIN customers c ON c.id=s.customer_id WHERE s.id=?", (sale_id,), one=True)
    if sale is None:
        abort(404)
    items = query("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,))
    payments = query(
        "SELECT p.*, t.status AS transfer_status, t.reference AS transfer_ref, "
        "t.bank AS transfer_bank, t.id AS tr_id FROM payments p "
        "LEFT JOIN transfers t ON t.id=p.transfer_id WHERE p.sale_id=?", (sale_id,))
    returns = query("SELECT * FROM sale_returns WHERE sale_id=? ORDER BY id", (sale_id,))
    return sale, items, payments, returns


@bp.route("/ventas/<int:sale_id>")
@login_required
def venta_detalle(sale_id):
    if not (can("pos.operar") or can("compras.consultar") or can("ventas.anular")):
        abort(403)
    sale, items, payments, returns = _venta_context(sale_id)
    ret_items = {}
    if returns:
        ids = ",".join("?" * len(returns))
        for r in query(f"SELECT * FROM sale_return_items WHERE return_id IN ({ids})",
                       [r["id"] for r in returns]):
            ret_items.setdefault(r["sale_item_id"], []).append(r)
    return render_template("venta_detalle.html", sale=sale, items=items,
                           payments=payments, returns=returns, ret_items=ret_items)


@bp.route("/ventas/<int:sale_id>/ticket")
@login_required
def venta_ticket(sale_id):
    if not (can("pos.operar") or can("compras.consultar") or can("ventas.anular")):
        abort(403)
    sale, items, payments, returns = _venta_context(sale_id)
    settings = {r["key"]: r["value"] for r in query("SELECT * FROM settings")}
    return render_template("ticket.html", sale=sale, items=items, payments=payments,
                           settings=settings)


@bp.route("/ventas/<int:sale_id>/anular", methods=["POST"])
@login_required
def venta_anular(sale_id):
    from .security import current_user

    reason = (request.form.get("reason") or "").strip()
    void_sale(sale_id, reason, current_user()["id"])
    if request.headers.get("Accept") == "application/json":
        return jsonify({"ok": True})
    from flask import flash

    flash("Venta anulada. El stock se repuso y los pagos se reversaron.", "ok")
    return redirect(url_for("pos.venta_detalle", sale_id=sale_id))


@bp.route("/ventas/<int:sale_id>/devolver", methods=["POST"])
@login_required
def venta_devolver(sale_id):
    data = request.get_json(silent=True)
    if data:
        from .security import current_user

        ret = create_return(sale_id, data.get("lines") or [],
                            current_user()["id"], data.get("reason") or "",
                            data.get("refund_method") or "efectivo")
        return jsonify({"ok": True, "id": ret["id"], "number": ret["number"],
                        "total": ret["total"]}), 201
    abort(400, description="Datos inválidos.")


# -------------------------------------------------------- TRANSFERENCIAS

@bp.route("/transferencias")
@login_required
@permission_required("transferencias.verificar")
def transferencias():
    estado = request.args.get("estado") or ""
    sql = ("SELECT t.*, s.number AS sale_number, c.name AS customer_name "
           "FROM transfers t LEFT JOIN sales s ON s.id=t.sale_id "
           "LEFT JOIN customers c ON c.id=t.customer_id WHERE 1=1")
    args = []
    if estado:
        sql += " AND t.status=?"
        args.append(estado)
    sql += " ORDER BY t.id DESC LIMIT 300"
    rows = query(sql, args)
    resumen = {r["status"]: r["c"] for r in query(
        "SELECT status, COUNT(*) AS c FROM transfers GROUP BY status")}
    return render_template("transferencias.html", transfers=rows, estado=estado,
                           resumen=resumen)


@bp.route("/transferencias/<int:tid>/estado", methods=["POST"])
@login_required
@permission_required("transferencias.verificar")
def transferencia_estado(tid):
    data = request.get_json(silent=True) or request.form.to_dict()
    decision = data.get("decision") or request.form.get("decision")
    note = data.get("note") or request.form.get("note") or ""
    if decision == "informada":
        from .services import mark_transfer_informed

        mark_transfer_informed(tid, None)
        tr = query("SELECT * FROM transfers WHERE id=?", (tid,), one=True)
    else:
        from .security import current_user

        tr = verify_transfer(tid, decision, current_user()["id"], note)
    if request.is_json:
        return jsonify({"ok": True, "status": tr["status"]})
    from flask import flash

    flash(f"Transferencia #{tid}: {tr['status']}.", "ok")
    return redirect(url_for("pos.transferencias"))


@bp.route("/api/cotizar", methods=["POST"])
@login_required
def api_cotizar():
    """Cálculo centralizado de totales de una venta (sin registrarla)."""
    from .services import quote_sale

    data = request.get_json(silent=True) or {}
    return jsonify(quote_sale(data.get("items") or []))
