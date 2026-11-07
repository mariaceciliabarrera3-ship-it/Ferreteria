"""Informes y estadísticas con datos reales + exportación CSV / Excel."""
import csv
import io

from flask import (Blueprint, abort, render_template, request, send_file)

from .db import now_date, query, round2
from .fiscal import sales_profit, stock_valuation
from .security import can, login_required

bp = Blueprint("reports", __name__)


def _rango():
    desde = request.args.get("desde") or now_date()[:7] + "-01"
    hasta = request.args.get("hasta") or now_date()
    return desde, hasta


def _ventas_por_vendedor(desde, hasta):
    return query(
        "SELECT u.username, COUNT(s.id) AS operaciones, COALESCE(SUM(s.total),0) AS total, "
        "COALESCE(SUM(s.total - s.cost_total),0) AS margen "
        "FROM sales s JOIN users u ON u.id=s.user_id "
        "WHERE s.status='activa' AND substr(s.datetime,1,10) BETWEEN ? AND ? "
        "GROUP BY u.id ORDER BY total DESC", (desde, hasta))


def _ventas_por_medio(desde, hasta):
    return query(
        "SELECT p.method, COUNT(*) AS n, COALESCE(SUM(p.amount),0) AS total "
        "FROM payments p JOIN sales s ON s.id=p.sale_id "
        "WHERE s.status='activa' AND substr(s.datetime,1,10) BETWEEN ? AND ? "
        "GROUP BY p.method ORDER BY total DESC", (desde, hasta))


def _top_productos(desde, hasta, asc=False, limit=15):
    order = "ASC" if asc else "DESC"
    return query(
        f"SELECT si.product_id, si.description, SUM(si.qty) AS qty, "
        f"SUM(si.line_total) AS total, SUM(si.qty * si.cost_snapshot) AS cost "
        f"FROM sale_items si JOIN sales s ON s.id=si.sale_id "
        f"WHERE s.status='activa' AND substr(s.datetime,1,10) BETWEEN ? AND ? "
        f"GROUP BY si.product_id ORDER BY qty {order} LIMIT ?", (desde, hasta, limit))


@bp.route("/reportes")
@login_required
def reportes():
    if not (can("pos.operar") or can("compras.consultar") or can("reportes.ganancias")):
        abort(403)
    tab = request.args.get("tab") or "ventas"
    desde, hasta = _rango()
    ctx = {"tab": tab, "desde": desde, "hasta": hasta}

    if tab == "ventas":
        ctx["por_dia"] = query(
            "SELECT substr(datetime,1,10) AS dia, COUNT(*) AS n, "
            "COALESCE(SUM(total),0) AS total, COALESCE(SUM(discount),0) AS descuentos "
            "FROM sales WHERE status='activa' AND substr(datetime,1,10) BETWEEN ? AND ? "
            "GROUP BY dia ORDER BY dia", (desde, hasta))
        ctx["por_vendedor"] = _ventas_por_vendedor(desde, hasta)
        ctx["por_medio"] = _ventas_por_medio(desde, hasta)
        ctx["totales"] = query(
            "SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS total, "
            "COALESCE(SUM(tax_total),0) AS impuestos, COALESCE(SUM(discount),0) AS desc "
            "FROM sales WHERE status='activa' AND substr(datetime,1,10) BETWEEN ? AND ?",
            (desde, hasta), one=True)
        maxd = max([r["total"] for r in ctx["por_dia"]] + [1])
        ctx["max_dia"] = maxd
    elif tab == "productos":
        ctx["top"] = _top_productos(desde, hasta)
        ctx["menos"] = _top_productos(desde, hasta, asc=True)
        ctx["stock"] = query(
            "SELECT code, description, stock, base_unit, avg_cost, sale_price, "
            "stock*avg_cost AS v_cost, stock*sale_price AS v_venta, stock_min "
            "FROM products WHERE active=1 ORDER BY description LIMIT 400")
        ctx["valor"] = stock_valuation()
    elif tab == "ganancias":
        if not can("reportes.ganancias"):
            abort(403)
        ctx["profit"] = sales_profit(desde, hasta)
        ctx["por_categoria"] = query(
            "SELECT COALESCE(c.name,'(sin categoría)') AS cat, "
            "SUM(si.line_total) AS ventas, SUM(si.qty*si.cost_snapshot) AS costo "
            "FROM sale_items si JOIN sales s ON s.id=si.sale_id "
            "LEFT JOIN products p ON p.id=si.product_id "
            "LEFT JOIN categories c ON c.id=p.category_id "
            "WHERE s.status='activa' AND substr(s.datetime,1,10) BETWEEN ? AND ? "
            "GROUP BY c.id ORDER BY ventas DESC", (desde, hasta))
        for r in ctx["por_categoria"]:
            pass
        ctx["margen_producto"] = query(
            "SELECT code, description, cost_price, sale_price, "
            "CASE WHEN cost_price>0 THEN ROUND((sale_price-cost_price)*100.0/cost_price,1) "
            "ELSE 0 END AS margen FROM products WHERE active=1 AND cost_price>0 "
            "ORDER BY margen DESC LIMIT 30")
        ctx["gastos"] = query(
            "SELECT COALESCE(SUM(amount),0) AS s FROM expenses "
            "WHERE substr(datetime,1,10) BETWEEN ? AND ?", (desde, hasta), one=True)
        ctx["compras"] = query(
            "SELECT COALESCE(SUM(total),0) AS s FROM purchases "
            "WHERE substr(datetime,1,10) BETWEEN ? AND ?", (desde, hasta), one=True)
    elif tab == "cuentas":
        if not (can("cuentas.consultar") or can("reportes.ganancias")):
            abort(403)
        ctx["cc"] = query(
            "SELECT c.id, c.name, c.doc, c.credit_limit, "
            "COALESCE(SUM(l.debit-l.credit),0) AS saldo "
            "FROM customers c LEFT JOIN customer_ledger l ON l.customer_id=c.id "
            "WHERE c.active=1 GROUP BY c.id HAVING saldo != 0 ORDER BY saldo DESC")
        ctx["pp"] = query(
            "SELECT s.id, s.name, s.cuit, COALESCE(SUM(l.debit-l.credit),0) AS saldo "
            "FROM suppliers s LEFT JOIN supplier_ledger l ON l.supplier_id=s.id "
            "WHERE s.active=1 GROUP BY s.id HAVING saldo != 0 ORDER BY saldo DESC")
        ctx["trans_pend"] = query(
            "SELECT t.*, s.number AS sale_number, c.name AS customer_name FROM transfers t "
            "LEFT JOIN sales s ON s.id=t.sale_id LEFT JOIN customers c ON c.id=t.customer_id "
            "WHERE t.status IN ('pendiente','informada') ORDER BY t.id")
        ctx["cc_total"] = sum(r["saldo"] for r in ctx["cc"])
        ctx["pp_total"] = sum(r["saldo"] for r in ctx["pp"])
    elif tab == "caja":
        if not (can("caja.operar") or can("caja.cerrar") or can("reportes.ganancias")):
            abort(403)
        ctx["sesiones"] = query(
            "SELECT cs.*, uo.username AS user_open_name FROM cash_sessions cs "
            "LEFT JOIN users uo ON uo.id=cs.user_open "
            "WHERE substr(cs.opened_at,1,10) BETWEEN ? AND ? ORDER BY cs.id DESC",
            (desde, hasta))
        ctx["flujo"] = query(
            "SELECT substr(datetime,1,10) AS dia, "
            "COALESCE(SUM(CASE WHEN type='ingreso' THEN amount END),0) AS ingresos, "
            "COALESCE(SUM(CASE WHEN type='egreso' THEN amount END),0) AS egresos "
            "FROM cash_movements WHERE substr(datetime,1,10) BETWEEN ? AND ? "
            "GROUP BY dia ORDER BY dia", (desde, hasta))
        ctx["compras"] = query(
            "SELECT COALESCE(SUM(total),0) AS s, COUNT(*) AS n FROM purchases "
            "WHERE pay_method='efectivo' AND substr(datetime,1,10) BETWEEN ? AND ?",
            (desde, hasta), one=True)
        ctx["gastos"] = query(
            "SELECT COALESCE(SUM(amount),0) AS s FROM expenses "
            "WHERE substr(datetime,1,10) BETWEEN ? AND ?", (desde, hasta), one=True)
    return render_template("reportes.html", **ctx)


def _csv_response(name, header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return send_file(io.BytesIO(buf.getvalue().encode("utf-8-sig")),
                     mimetype="text/csv", as_attachment=True,
                     download_name=f"{name}_{now_date()}.csv")


@bp.route("/reportes/exportar")
@login_required
def exportar():
    tipo = request.args.get("tipo") or ""
    desde, hasta = _rango()
    if tipo == "ventas":
        rows = [tuple(r) for r in query(
            "SELECT s.number, s.datetime, u.username, COALESCE(c.name,''), s.subtotal, "
            "s.discount, s.tax_total, s.total, s.cost_total, s.status, s.payment_status "
            "FROM sales s JOIN users u ON u.id=s.user_id "
            "LEFT JOIN customers c ON c.id=s.customer_id "
            "WHERE substr(s.datetime,1,10) BETWEEN ? AND ? ORDER BY s.id", (desde, hasta))]
        return _csv_response("ventas", ["Comprobante", "Fecha", "Vendedor", "Cliente",
                                        "Subtotal", "Descuentos", "Impuestos", "Total",
                                        "Costo", "Estado", "Cobro"], rows)
    if tipo == "stock":
        rows = [tuple(r) for r in query(
            "SELECT code, description, base_unit, stock, stock_min, avg_cost, sale_price, "
            "stock*avg_cost, stock*sale_price, location FROM products WHERE active=1 "
            "ORDER BY code")]
        return _csv_response("stock", ["Codigo", "Descripcion", "Unidad", "Stock",
                                       "StockMin", "CostoProm", "PrecioVenta",
                                       "ValorCosto", "ValorVenta", "Ubicacion"], rows)
    if tipo == "movimientos":
        rows = [tuple(r) for r in query(
            "SELECT m.datetime, p.code, p.description, m.type, m.qty, m.stock_after, "
            "COALESCE(u.username,''), m.reason FROM stock_movements m "
            "JOIN products p ON p.id=m.product_id LEFT JOIN users u ON u.id=m.user_id "
            "WHERE substr(m.datetime,1,10) BETWEEN ? AND ? ORDER BY m.id", (desde, hasta))]
        return _csv_response("movimientos", ["Fecha", "Codigo", "Producto", "Tipo",
                                             "Cantidad", "StockResultante", "Usuario",
                                             "Motivo"], rows)
    if tipo == "ganancias":
        if not can("reportes.ganancias"):
            abort(403)
        p = sales_profit(desde, hasta)
        return _csv_response("ganancias", ["Concepto", "Valor"],
                             [("Ventas", p["sales"]), ("Costo mercaderia", p["cost"]),
                              ("Ganancia bruta", p["profit"]), ("Margen %", p["margin"]),
                              ("Operaciones", p["count"])])
    if tipo == "cuentas":
        rows = [tuple(r) for r in query(
            "SELECT c.name, c.doc, COALESCE(SUM(l.debit-l.credit),0) FROM customers c "
            "LEFT JOIN customer_ledger l ON l.customer_id=c.id "
            "GROUP BY c.id HAVING 3 != 0 ORDER BY 3 DESC")]
        return _csv_response("cuentas_por_cobrar", ["Cliente", "Documento", "Saldo"], rows)
    abort(400, description="Tipo de exportación inválido.")


@bp.route("/reportes/excel")
@login_required
def excel():
    """Genera un .xlsx real con openpyxl (libre, sin servicios externos)."""
    if not (can("pos.operar") or can("compras.consultar")):
        abort(403)
    desde, hasta = _rango()
    try:
        from openpyxl import Workbook
    except ImportError:  # pragma: no cover
        abort(500, description="openpyxl no está instalado en el servidor.")
    wb = Workbook()
    ws = wb.active
    ws.title = "Ventas"
    ws.append(["Comprobante", "Fecha", "Vendedor", "Cliente", "Total", "Estado", "Cobro"])
    for r in query(
            "SELECT s.number, s.datetime, u.username, COALESCE(c.name,''), s.total, "
            "s.status, s.payment_status FROM sales s JOIN users u ON u.id=s.user_id "
            "LEFT JOIN customers c ON c.id=s.customer_id "
            "WHERE substr(s.datetime,1,10) BETWEEN ? AND ? ORDER BY s.id", (desde, hasta)):
        ws.append(list(r))
    ws2 = wb.create_sheet("Stock")
    ws2.append(["Codigo", "Descripcion", "Unidad", "Stock", "CostoProm", "PrecioVenta",
                "ValorCosto", "ValorVenta"])
    for r in query(
            "SELECT code, description, base_unit, stock, avg_cost, sale_price, "
            "stock*avg_cost, stock*sale_price FROM products WHERE active=1 ORDER BY code"):
        ws2.append(list(r))
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return send_file(out, mimetype=(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        as_attachment=True, download_name=f"informe_{desde}_{hasta}.xlsx")
