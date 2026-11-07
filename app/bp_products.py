"""Productos, conversiones de unidades, inventario y movimientos."""
import csv
import io

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, send_file, url_for)

from . import fiscal
from .db import execute, insert, now_date, now_iso, query, round2
from .security import audit, can, login_required, permission_required
from .services import apply_movement, sale_units_for

bp = Blueprint("products", __name__)

PRICE_FIELDS = ("cost_price", "sale_price", "wholesale_price", "special_price")


def _categories():
    return query("SELECT * FROM categories WHERE active=1 ORDER BY name")


def _suppliers():
    return query("SELECT id, name FROM suppliers WHERE active=1 ORDER BY name")


def _units():
    return query("SELECT * FROM units ORDER BY name")


def _get_product(pid):
    p = query(
        "SELECT p.*, c.name AS category_name, s.name AS supplier_name "
        "FROM products p LEFT JOIN categories c ON c.id=p.category_id "
        "LEFT JOIN suppliers s ON s.id=p.supplier_id WHERE p.id=?", (pid,), one=True)
    if p is None:
        abort(404)
    return p


@bp.route("/productos")
@login_required
def lista():
    if not (can("productos.gestionar") or can("pos.operar")):
        abort(403)
    q = (request.args.get("q") or "").strip()
    cat = request.args.get("categoria") or ""
    filtro = request.args.get("filtro") or ""
    sql = ("SELECT p.*, c.name AS category_name FROM products p "
           "LEFT JOIN categories c ON c.id=p.category_id WHERE p.active=1")
    args = []
    if q:
        sql += " AND (p.description LIKE ? OR p.code LIKE ? OR p.barcode LIKE ? OR p.brand LIKE ?)"
        like = f"%{q}%"
        args += [like, like, like, like]
    if cat:
        sql += " AND p.category_id=?"
        args.append(int(cat))
    if filtro == "bajo":
        sql += " AND p.stock <= p.stock_min AND p.stock_min > 0"
    elif filtro == "sin":
        sql += " AND p.stock <= 0"
    sql += " ORDER BY p.description LIMIT 400"
    rows = query(sql, args)
    val = fiscal.stock_valuation()
    return render_template("productos.html", productos=rows, q=q, cat=cat,
                           filtro=filtro, categories=_categories(), valor=val)


@bp.route("/productos/nuevo", methods=["GET", "POST"])
@login_required
@permission_required("productos.gestionar")
def nuevo():
    if request.method == "POST":
        f = request.form
        try:
            stock_inicial = round2(float(f.get("stock_inicial") or 0))
        except ValueError:
            abort(400, description="Stock inicial inválido.")
        code = (f.get("code") or "").strip()
        desc = (f.get("description") or "").strip()
        if not code or not desc:
            flash("Código y descripción son obligatorios.", "error")
            return render_template("producto_form.html", p=None, categories=_categories(),
                                   suppliers=_suppliers(), units=_units())
        if query("SELECT id FROM products WHERE code=?", (code,), one=True):
            flash("Ya existe un producto con ese código.", "error")
            return render_template("producto_form.html", p=None, categories=_categories(),
                                   suppliers=_suppliers(), units=_units())
        base_unit = (f.get("base_unit") or "unidad").strip().lower()
        _ensure_unit(base_unit)
        pid = insert(
            "INSERT INTO products (code, barcode, description, brand, model, category_id, "
            "supplier_id, base_unit, default_sale_unit, cost_price, avg_cost, sale_price, "
            "wholesale_price, special_price, stock, stock_min, stock_max, location, "
            "updated_at, active, notes, tax_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (code, (f.get("barcode") or "").strip(), desc,
             (f.get("brand") or "").strip(), (f.get("model") or "").strip(),
             int(f["category_id"]) if f.get("category_id") else None,
             int(f["supplier_id"]) if f.get("supplier_id") else None,
             base_unit, (f.get("default_sale_unit") or base_unit).strip().lower(),
             round2(f.get("cost_price") or 0), round2(f.get("cost_price") or 0),
             round2(f.get("sale_price") or 0), round2(f.get("wholesale_price") or 0),
             round2(f.get("special_price") or 0), 0,
             round2(f.get("stock_min") or 0), round2(f.get("stock_max") or 0),
             (f.get("location") or "").strip(), now_iso(), 1,
             (f.get("notes") or "").strip(),
             int(f["tax_id"]) if f.get("tax_id") else None),
        )
        # Conversiones de unidades (por producto)
        _save_conversions(pid, f)
        if stock_inicial > 0:
            apply_movement(pid, stock_inicial, "inventario_inicial", _uid(),
                           "Stock inicial del alta", "product", pid, allow_negative=False)
            execute("UPDATE products SET avg_cost=?, cost_price=? WHERE id=? AND cost_price=0",
                    (round2(f.get("cost_price") or 0), round2(f.get("cost_price") or 0), pid))
        fiscal.price_history_save(pid, "sale_price", 0, f.get("sale_price") or 0, _uid(), "Alta de producto")
        audit("crear", "producto", pid, {"code": code, "description": desc})
        flash(f"Producto '{desc}' dado de alta correctamente.", "ok")
        return redirect(url_for("products.detalle", pid=pid))
    return render_template("producto_form.html", p=None, categories=_categories(),
                           suppliers=_suppliers(), units=_units())


def _uid():
    from .security import current_user

    u = current_user()
    return u["id"] if u else None


def _ensure_unit(name):
    if not name:
        return
    execute("INSERT OR IGNORE INTO units (name) VALUES (?)", (name,))


def _save_conversions(pid, form):
    """Guarda conversiones: conv_unit[i], conv_factor[i]."""
    execute("DELETE FROM unit_conversions WHERE product_id=?", (pid,))
    units = form.getlist("conv_unit")
    factors = form.getlist("conv_factor")
    for u, f in zip(units, factors):
        u = (u or "").strip().lower()
        try:
            factor = float((f or "").replace(",", "."))
        except ValueError:
            continue
        if u and factor > 0:
            _ensure_unit(u)
            execute(
                "INSERT OR REPLACE INTO unit_conversions (product_id, unit, factor) VALUES (?, ?, ?)",
                (pid, u, factor))


@bp.route("/productos/<int:pid>", methods=["GET", "POST"])
@login_required
def detalle(pid):
    p = _get_product(pid)
    if request.method == "POST":
        if not can("productos.gestionar"):
            abort(403)
        f = request.form
        _ensure_unit((f.get("base_unit") or "").strip().lower())
        updates, args = [], []
        changes = {}
        for field, form_field in (("code", "code"), ("barcode", "barcode"),
                                  ("description", "description"), ("brand", "brand"),
                                  ("model", "model"), ("location", "location"),
                                  ("notes", "notes"), ("base_unit", "base_unit"),
                                  ("default_sale_unit", "default_sale_unit")):
            new = (f.get(form_field) or "").strip()
            if field in ("base_unit", "default_sale_unit"):
                new = new.lower()
            if field == "description" and not new:
                continue
            if str(p[field] or "") != new:
                updates.append(f"{field}=?")
                args.append(new)
                changes[field] = {"old": p[field], "new": new}
        if f.get("category_id"):
            if p["category_id"] != int(f["category_id"]):
                updates.append("category_id=?")
                args.append(int(f["category_id"]))
        if f.get("supplier_id"):
            if p["supplier_id"] != int(f["supplier_id"]):
                updates.append("supplier_id=?")
                args.append(int(f["supplier_id"]))
        for field in ("cost_price", "sale_price", "wholesale_price", "special_price",
                      "stock_min", "stock_max"):
            try:
                new = round2(f.get(field))
            except (TypeError, ValueError):
                abort(400, description=f"Valor inválido en {field}.")
            if field in ("cost_price", "sale_price", "wholesale_price", "special_price") \
                    and new != float(p[field] or 0):
                if not can("precios.modificar"):
                    abort(403, description="No tiene permiso para modificar precios de venta o costo.")
                fiscal.price_history_save(pid, field, p[field], new, _uid(), "Edición manual")
                changes[field] = {"old": p[field], "new": new}
            if new != float(p[field] or 0):
                updates.append(f"{field}=?")
                args.append(new)
        if f.get("tax_id") is not None and f.get("tax_id") != "":
            updates.append("tax_id=?")
            args.append(int(f["tax_id"]))
        updates.append("updated_at=?")
        args.append(now_iso())
        if updates:
            execute(f"UPDATE products SET {', '.join(updates)} WHERE id=?", (*args, pid))
        _save_conversions(pid, f)
        audit("modificar", "producto", pid, changes if changes else "sin cambios de precio")
        flash("Producto actualizado.", "ok")
        return redirect(url_for("products.detalle", pid=pid))

    conversions = query("SELECT * FROM unit_conversions WHERE product_id=? ORDER BY unit", (pid,))
    movimientos = query(
        "SELECT m.*, u.username FROM stock_movements m "
        "LEFT JOIN users u ON u.id=m.user_id WHERE m.product_id=? ORDER BY m.id DESC LIMIT 50",
        (pid,))
    precios = query(
        "SELECT ph.*, u.username FROM price_history ph "
        "LEFT JOIN users u ON u.id=ph.user_id WHERE ph.product_id=? ORDER BY ph.id DESC LIMIT 30",
        (pid,))
    ventas_mes = query(
        "SELECT COUNT(*) AS c, COALESCE(SUM(si.qty),0) AS q FROM sale_items si "
        "JOIN sales s ON s.id=si.sale_id WHERE si.product_id=? AND s.status='activa' "
        "AND substr(s.datetime,1,10)>=date('now','start of month')", (pid,), one=True)
    margin = fiscal.margin_pct(p["cost_price"], p["sale_price"])
    return render_template("producto_detalle.html", p=p, conversions=conversions,
                           movimientos=movimientos, precios=precios, margin=margin,
                           ventas_mes=ventas_mes, categories=_categories(),
                           suppliers=_suppliers(), units=_units(),
                           taxes=query("SELECT id, name FROM taxes ORDER BY name"),
                           sale_units=sale_units_for(p))


@bp.route("/productos/<int:pid>/inactivar", methods=["POST"])
@login_required
@permission_required("productos.gestionar")
def inactivar(pid):
    p = _get_product(pid)
    nuevo = 0 if p["active"] else 1
    execute("UPDATE products SET active=?, updated_at=? WHERE id=?", (nuevo, now_iso(), pid))
    audit("estado", "producto", pid, {"active": nuevo})
    flash("Producto " + ("activado" if nuevo else "desactivado") + ".", "ok")
    return redirect(url_for("products.lista"))


@bp.route("/inventario/ajuste", methods=["GET", "POST"])
@login_required
@permission_required("stock.modificar")
def ajuste():
    if request.method == "POST":
        f = request.form
        try:
            pid = int(f.get("product_id"))
            qty = round2(float(f.get("qty")))
        except (TypeError, ValueError):
            abort(400, description="Producto o cantidad inválidos.")
        mtype = f.get("type")
        if mtype not in ("ajuste", "rotura", "perdida", "entrada", "inventario"):
            abort(400, description="Tipo de movimiento inválido.")
        if qty == 0:
            abort(400, description="La cantidad no puede ser cero.")
        delta = qty if mtype in ("entrada", "inventario") else -abs(qty)
        if mtype == "ajuste":
            # ajuste = diferencia de conteo físico: qty = stock real contado
            p = query("SELECT stock FROM products WHERE id=?", (pid,), one=True)
            if p is None:
                abort(404)
            delta = round2(qty - float(p["stock"]))
        reason = (f.get("reason") or "").strip()
        if not reason:
            flash("Debe indicar el motivo del movimiento.", "error")
            return redirect(url_for("products.ajuste"))
        apply_movement(pid, delta, mtype, _uid(), reason, "manual", None,
                       allow_negative=False)
        audit("stock", "producto", pid, {"type": mtype, "delta": delta, "reason": reason})
        flash("Movimiento de stock registrado.", "ok")
        return redirect(url_for("products.movimientos"))
    return render_template("ajuste_stock.html",
                           productos=query("SELECT id, code, description, stock, base_unit "
                                           "FROM products WHERE active=1 ORDER BY description LIMIT 500"))


@bp.route("/inventario/movimientos")
@login_required
def movimientos():
    if not (can("stock.modificar") or can("productos.gestionar") or can("compras.consultar")):
        abort(403)
    q = (request.args.get("q") or "").strip()
    tipo = request.args.get("tipo") or ""
    sql = ("SELECT m.*, p.description, p.code, p.base_unit, u.username "
           "FROM stock_movements m JOIN products p ON p.id=m.product_id "
           "LEFT JOIN users u ON u.id=m.user_id WHERE 1=1")
    args = []
    if q:
        sql += " AND (p.description LIKE ? OR p.code LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if tipo:
        sql += " AND m.type=?"
        args.append(tipo)
    sql += " ORDER BY m.id DESC LIMIT 300"
    return render_template("movimientos.html", movimientos=query(sql, args), q=q, tipo=tipo)


@bp.route("/inventario/alertas")
@login_required
def alertas():
    bajos = query(
        "SELECT p.*, c.name AS category_name FROM products p "
        "LEFT JOIN categories c ON c.id=p.category_id "
        "WHERE p.active=1 AND p.stock <= p.stock_min AND p.stock_min > 0 "
        "ORDER BY (p.stock - p.stock_min)")
    sin = query("SELECT * FROM products WHERE active=1 AND stock<=0 ORDER BY description")
    # Productos sin movimiento en 90 días
    sin_mov = query(
        "SELECT p.* FROM products p WHERE p.active=1 AND p.stock > 0 AND NOT EXISTS "
        "(SELECT 1 FROM stock_movements m WHERE m.product_id=p.id "
        "AND m.datetime >= datetime('now','-90 days')) ORDER BY p.description LIMIT 100")
    rotacion = query(
        "SELECT p.description, p.stock, p.base_unit, "
        "COALESCE(SUM(CASE WHEN m.type='venta' THEN -m.qty ELSE 0 END),0) AS vendidos "
        "FROM products p LEFT JOIN stock_movements m ON m.product_id=p.id "
        "AND m.datetime >= datetime('now','-30 days') "
        "WHERE p.active=1 GROUP BY p.id HAVING vendidos > 0 ORDER BY vendidos DESC LIMIT 15")
    return render_template("alertas.html", bajos=bajos, sin=sin, sin_mov=sin_mov,
                           rotacion=rotacion)


@bp.route("/productos/exportar")
@login_required
def exportar():
    if not (can("productos.gestionar") or can("compras.consultar")):
        abort(403)
    rows = query(
        "SELECT p.code, p.barcode, p.description, p.brand, p.model, c.name AS categoria, "
        "p.base_unit, p.cost_price, p.avg_cost, p.sale_price, p.wholesale_price, "
        "p.stock, p.stock_min, p.stock_max, p.location, p.active "
        "FROM products p LEFT JOIN categories c ON c.id=p.category_id ORDER BY p.code")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Codigo", "CodigoBarras", "Descripcion", "Marca", "Modelo", "Categoria",
                "UnidadBase", "Costo", "CostoPromedio", "PrecioVenta", "PrecioMayorista",
                "Stock", "StockMin", "StockMax", "Ubicacion", "Activo"])
    for r in rows:
        w.writerow([r["code"], r["barcode"], r["description"], r["brand"], r["model"],
                    r["categoria"] or "", r["base_unit"], r["cost_price"], r["avg_cost"],
                    r["sale_price"], r["wholesale_price"], r["stock"], r["stock_min"],
                    r["stock_max"], r["location"], "si" if r["active"] else "no"])
    buf.seek(0)
    audit("exportar", "productos", None, {"rows": len(rows)})
    return send_file(io.BytesIO(buf.getvalue().encode("utf-8-sig")),
                     mimetype="text/csv", as_attachment=True,
                     download_name="productos.csv")


@bp.route("/productos/importar", methods=["POST"])
@login_required
@permission_required("productos.gestionar")
def importar():
    """Carga masiva de productos y stock desde CSV o Excel (.xlsx).

    Columnas (sinóminos aceptados): codigo, descripcion, marca, unidad,
    precio compra, precio venta, stock minimo, cantidad.
    Columna opcional «accion_stock»: sumar | reemplazar (solo productos
    existentes) — el stock NUNCA se pisa sin dejar un movimiento auditable.
    """
    f = request.files.get("archivo")
    if not f or not (f.filename.lower().endswith(".csv") or
                     f.filename.lower().endswith(".xlsx")):
        flash("Adjunte un archivo CSV o Excel (.xlsx).", "error")
        return redirect(url_for("products.lista"))
    rows = _leer_filas_import(f)
    if rows is None:
        flash("No se pudo leer el archivo (formato no reconocido).", "error")
        return redirect(url_for("products.lista"))
    creados = actualizados = stock_ok = errores = 0
    for row in rows:
        code = row.get("codigo") or row.get("code")
        desc = row.get("descripcion") or row.get("description") or row.get("nombre")
        if not code:
            continue
        try:
            existente = query("SELECT * FROM products WHERE code=?", (code,), one=True)
            if existente:
                execute(
                    "UPDATE products SET description=?, brand=?, stock_min=?, sale_price=?, "
                    "cost_price=?, updated_at=? WHERE id=?",
                    (desc or existente["description"],
                     row.get("marca", existente["brand"]),
                     _num(row.get("stock minimo"), existente["stock_min"]),
                     _num(row.get("precio venta"), existente["sale_price"]),
                     _num(row.get("precio compra"), existente["cost_price"]),
                     now_iso(), existente["id"]))
                actualizados += 1
                accion = (row.get("accion_stock") or "").strip().lower()
                if accion in ("sumar", "reemplazar") and row.get("cantidad") not in (None, ""):
                    cantidad = _num(row.get("cantidad"), 0)
                    if accion == "sumar":
                        delta = cantidad
                        mtype = "entrada"
                    else:
                        delta = cantidad - float(existente["stock"])
                        mtype = "ajuste"
                    if abs(delta) > 1e-9:
                        apply_movement(existente["id"], delta, mtype, _uid(),
                                       f"Carga masiva de archivo ({f.filename})",
                                       "import", None, allow_negative=False)
                        stock_ok += 1
            else:
                if not desc:
                    errores += 1
                    continue
                base = (row.get("unidad") or "unidad").strip().lower()
                _ensure_unit(base)
                cost = _num(row.get("precio compra"), 0)
                inicial = _num(row.get("cantidad"), 0)
                pid = insert(
                    "INSERT INTO products (code, description, brand, base_unit, default_sale_unit, "
                    "cost_price, avg_cost, sale_price, stock, stock_min, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,0,?,?)",
                    (code, desc, row.get("marca", ""), base, base, cost, cost,
                     _num(row.get("precio venta"), 0),
                     _num(row.get("stock minimo"), 0), now_iso()))
                if inicial > 0:
                    apply_movement(pid, inicial, "inventario_inicial", _uid(),
                                   f"Stock inicial por carga masiva ({f.filename})",
                                   "import", None)
                    stock_ok += 1
                creados += 1
        except Exception:  # noqa: BLE001 — una fila mala no frena la carga
            errores += 1
    audit("importar", "productos", None, {"creados": creados, "actualizados": actualizados,
                                          "stock": stock_ok, "errores": errores})
    flash(f"Carga finalizada: {creados} productos creados, {actualizados} actualizados, "
          f"{stock_ok} ajustes de stock con movimiento auditado"
          + (f", {errores} filas con error." if errores else "."), "ok")
    return redirect(url_for("products.lista"))


def _num(v, default=0.0):
    """Interpreta números en formato argentino ('1.234,56') o inglés ('1,234.56')."""
    if v is None or v == "":
        return float(default)
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return float(default)


def _leer_filas_import(f):
    """Devuelve lista de dicts (claves en minúsculas) desde CSV o XLSX."""
    name = (f.filename or "").lower()
    if name.endswith(".xlsx"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            return None
        wb = load_workbook(f.stream, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        data = list(ws.iter_rows(values_only=True))
        wb.close()
        if not data:
            return None
        headers = [str(h or "").strip().lower() for h in data[0]]
        out = []
        for r in data[1:]:
            if r is None or all(c is None or str(c).strip() == "" for c in r):
                continue
            out.append({headers[i]: ("" if r[i] is None else str(r[i]).strip())
                        for i in range(min(len(headers), len(r)))})
        return out
    try:
        content = f.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        f.stream.seek(0)
        content = f.read().decode("latin-1")
    reader = csv.DictReader(io.StringIO(content))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            for row in reader]
    try:
        content = f.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        content = f.read().decode("latin-1")
    reader = csv.DictReader(io.StringIO(content))
    creados = actualizados = 0
    for row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        code = row.get("codigo") or row.get("code")
        desc = row.get("descripcion") or row.get("description") or row.get("nombre")
        if not code or not desc:
            continue
        existente = query("SELECT id FROM products WHERE code=?", (code,), one=True)
        if existente:
            execute(
                "UPDATE products SET description=?, brand=?, stock_min=?, sale_price=?, "
                "cost_price=?, updated_at=? WHERE id=?",
                (desc, row.get("marca", ""), float(row.get("stock minimo") or 0),
                 float(row.get("precio venta") or 0), float(row.get("precio compra") or 0),
                 now_iso(), existente["id"]))
            actualizados += 1
        else:
            base = (row.get("unidad") or "unidad").lower()
            _ensure_unit(base)
            execute(
                "INSERT INTO products (code, description, brand, base_unit, default_sale_unit, "
                "cost_price, avg_cost, sale_price, stock, stock_min, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (code, desc, row.get("marca", ""), base, base,
                 float(row.get("precio compra") or 0), float(row.get("precio compra") or 0),
                 float(row.get("precio venta") or 0), float(row.get("cantidad") or 0),
                 float(row.get("stock minimo") or 0), now_iso()))
            creados += 1
    audit("importar", "productos", None, {"creados": creados, "actualizados": actualizados})
    flash(f"Importación finalizada: {creados} productos creados, {actualizados} actualizados.", "ok")
    return redirect(url_for("products.lista"))
