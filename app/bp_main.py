"""Panel principal (dashboard) y búsqueda global."""
from flask import Blueprint, jsonify, render_template, request

from .db import now_date, query, round2
from .fiscal import sales_profit, stock_valuation
from .security import login_required

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def dashboard():
    today = now_date()
    month = today[:7] + "-01"

    ventas_hoy = query(
        "SELECT COALESCE(SUM(total),0) AS s, COUNT(*) AS c FROM sales "
        "WHERE status='activa' AND substr(datetime,1,10)=?", (today,), one=True)
    ventas_mes = query(
        "SELECT COALESCE(SUM(total),0) AS s, COUNT(*) AS c FROM sales "
        "WHERE status='activa' AND substr(datetime,1,10)>=?", (month,), one=True)
    low_stock = query(
        "SELECT COUNT(*) AS c FROM products WHERE active=1 AND stock <= stock_min AND stock_min > 0",
        one=True)["c"]
    sin_stock = query(
        "SELECT COUNT(*) AS c FROM products WHERE active=1 AND stock <= 0", one=True)["c"]
    transfer_pend = query(
        "SELECT COUNT(*) AS c, COALESCE(SUM(amount),0) AS s FROM transfers "
        "WHERE status IN ('pendiente','informada')", one=True)
    caja = query("SELECT * FROM cash_sessions WHERE status='abierta' ORDER BY id DESC", one=True)
    cc_saldo = query(
        "SELECT COALESCE(SUM(debit-credit),0) AS s FROM customer_ledger", one=True)["s"]
    prov_saldo = query(
        "SELECT COALESCE(SUM(debit-credit),0) AS s FROM supplier_ledger", one=True)["s"]
    valor = stock_valuation()
    profit = sales_profit(month, today)

    # Ventas de los últimos 7 días (gráficos con datos reales)
    dias = query(
        "SELECT substr(datetime,1,10) AS dia, COALESCE(SUM(total),0) AS total FROM sales "
        "WHERE status='activa' AND substr(datetime,1,10) >= date(?, '-6 days') "
        "GROUP BY dia ORDER BY dia", (today,))
    serie = []
    base = [d["dia"] for d in dias]
    from datetime import date, timedelta

    d0 = date.fromisoformat(today) - timedelta(days=6)
    for i in range(7):
        d = (d0 + timedelta(days=i)).isoformat()
        v = next((x["total"] for x in dias if x["dia"] == d), 0)
        serie.append({"dia": d, "total": round2(v)})
    maxv = max([x["total"] for x in serie] + [1])

    top = query(
        "SELECT si.description, SUM(si.qty) AS q, SUM(si.line_total) AS t "
        "FROM sale_items si JOIN sales s ON s.id=si.sale_id "
        "WHERE s.status='activa' AND substr(s.datetime,1,10)>=? "
        "GROUP BY si.product_id ORDER BY q DESC LIMIT 5", (month,))

    ultimos = query(
        "SELECT s.id, s.number, s.datetime, s.total, s.payment_status, u.username "
        "FROM sales s JOIN users u ON u.id=s.user_id "
        "ORDER BY s.id DESC LIMIT 8")

    movs = query(
        "SELECT m.*, p.description FROM stock_movements m "
        "JOIN products p ON p.id=m.product_id ORDER BY m.id DESC LIMIT 8")

    return render_template(
        "dashboard.html",
        ventas_hoy=ventas_hoy, ventas_mes=ventas_mes, low_stock=low_stock,
        sin_stock=sin_stock, transfer_pend=transfer_pend, caja=caja,
        cc_saldo=cc_saldo, prov_saldo=prov_saldo, valor=valor, profit=profit,
        serie=serie, serie_max=maxv, top=top, ultimos=ultimos, movs=movs,
    )


@bp.route("/api/buscar")
@login_required
def api_buscar():
    """Búsqueda global: productos (nombre/código/barcode) y clientes."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"productos": [], "clientes": []})
    like = f"%{q}%"
    prods = query(
        "SELECT id, code, barcode, description, stock, base_unit, sale_price FROM products "
        "WHERE active=1 AND (description LIKE ? OR code LIKE ? OR barcode LIKE ? "
        "OR brand LIKE ?) ORDER BY description LIMIT 8",
        (like, like, like, like))
    clis = query(
        "SELECT id, name, doc FROM customers WHERE active=1 AND (name LIKE ? OR doc LIKE ?) "
        "ORDER BY name LIMIT 5", (like, like))
    return jsonify({
        "productos": [dict(r) for r in prods],
        "clientes": [dict(r) for r in clis],
    })
