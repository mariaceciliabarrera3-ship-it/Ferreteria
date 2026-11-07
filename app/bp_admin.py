"""Administración: clientes/cuentas corrientes, caja, gastos, usuarios,
configuración (negocio, impuestos, categorías, unidades, transferencias),
licencias, auditoría y copias de seguridad."""
import json
from datetime import date, timedelta

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, send_file, url_for)

from . import fiscal, license as lic
from .db import execute, insert, now_date, now_iso, query, round2
from .security import (ALL_PERMS, ROLE_DEFAULTS, audit, can, current_user,
                       hash_password, login_required, permission_required)
from .services import (assert_ops_allowed, cash_close, cash_expected,
                       cash_movement, cash_open, customer_balance,
                       customer_payment, open_cash_session)

bp = Blueprint("admin", __name__)


def _uid():
    u = current_user()
    return u["id"] if u else None


# ------------------------------------------------- CLIENTES / CTA. CTE.

@bp.route("/clientes")
@login_required
def clientes():
    if not (can("clientes.gestionar") or can("cuentas.consultar") or can("pos.operar")):
        abort(403)
    q = (request.args.get("q") or "").strip()
    sql = "SELECT * FROM customers WHERE active=1"
    args = []
    if q:
        sql += " AND (name LIKE ? OR doc LIKE ?)"
        args = [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY name LIMIT 300"
    rows = query(sql, args)
    saldos = {r["customer_id"]: r["s"] for r in query(
        "SELECT customer_id, COALESCE(SUM(debit-credit),0) AS s FROM customer_ledger "
        "GROUP BY customer_id")}
    return render_template("clientes.html", clientes=rows, q=q, saldos=saldos)


@bp.route("/clientes/nuevo", methods=["GET", "POST"])
@login_required
@permission_required("clientes.gestionar")
def cliente_nuevo():
    if request.method == "POST":
        f = request.form
        name = (f.get("name") or "").strip()
        if not name:
            flash("El nombre es obligatorio.", "error")
            return redirect(url_for("admin.cliente_nuevo"))
        try:
            limit = round2(f.get("credit_limit") or 0)
        except (TypeError, ValueError):
            limit = 0
        cid = insert(
            "INSERT INTO customers (name, doc, address, phone, email, credit_limit, notes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (name, f.get("doc", "").strip(), f.get("address", "").strip(),
             f.get("phone", "").strip(), f.get("email", "").strip(), limit,
             f.get("notes", "").strip(), now_iso()),
        )
        audit("crear", "cliente", cid, {"name": name})
        flash("Cliente dado de alta.", "ok")
        return redirect(url_for("admin.cliente_detalle", cid=cid))
    return render_template("cliente_form.html", c=None)


@bp.route("/clientes/<int:cid>", methods=["GET", "POST"])
@login_required
def cliente_detalle(cid):
    if not (can("clientes.gestionar") or can("cuentas.consultar") or can("pos.operar")):
        abort(403)
    c = query("SELECT * FROM customers WHERE id=?", (cid,), one=True)
    if c is None:
        abort(404)
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        if action == "cobro":
            try:
                res = customer_payment(cid, f.get("amount"), f.get("method") or "efectivo",
                                       _uid(), f.get("notes") or "")
                if res.get("pending_transfer"):
                    flash("Cobro por transferencia registrado PENDIENTE DE VERIFICACIÓN: "
                          "no se acreditará hasta que un administrador lo verifique.", "ok")
                else:
                    flash("Cobro registrado.", "ok")
            except Exception as e:  # noqa: BLE001
                flash(str(getattr(e, "description", e)), "error")
            return redirect(url_for("admin.cliente_detalle", cid=cid))
        if not can("clientes.gestionar"):
            abort(403)
        try:
            limit = round2(f.get("credit_limit"))
        except (TypeError, ValueError):
            limit = c["credit_limit"]
        execute(
            "UPDATE customers SET name=?, doc=?, address=?, phone=?, email=?, credit_limit=?, notes=? "
            "WHERE id=?",
            ((f.get("name") or c["name"]).strip(), f.get("doc", c["doc"]),
             f.get("address", c["address"]), f.get("phone", c["phone"]),
             f.get("email", c["email"]), limit, f.get("notes", c["notes"]), cid))
        audit("modificar", "cliente", cid, {})
        flash("Cliente actualizado.", "ok")
        return redirect(url_for("admin.cliente_detalle", cid=cid))

    ventas = query(
        "SELECT * FROM sales WHERE customer_id=? ORDER BY id DESC LIMIT 50", (cid,))
    movs = query(
        "SELECT * FROM customer_ledger WHERE customer_id=? ORDER BY id DESC LIMIT 80", (cid,))
    pagos = query(
        "SELECT * FROM customer_payments WHERE customer_id=? ORDER BY id DESC LIMIT 50", (cid,))
    saldo = customer_balance(cid)
    limit = float(c["credit_limit"] or 0)
    return render_template("cliente_detalle.html", c=c, ventas=ventas, movs=movs,
                           pagos=pagos, saldo=saldo, limit=limit,
                           excede=(limit > 0 and saldo > limit))


# ----------------------------------------------------------------- CAJA

@bp.route("/caja")
@login_required
def caja():
    if not (can("caja.operar") or can("caja.cerrar")):
        abort(403)
    session = open_cash_session()
    movs = []
    expected = None
    if session:
        movs = query(
            "SELECT m.*, u.username FROM cash_movements m "
            "LEFT JOIN users u ON u.id=m.user_id WHERE m.session_id=? ORDER BY m.id",
            (session["id"],))
        expected = cash_expected(session)
    return render_template("caja.html", session=session, movs=movs, expected=expected)


@bp.route("/caja/abrir", methods=["POST"])
@login_required
@permission_required("caja.operar")
def caja_abrir():
    try:
        cash_open(_uid(), request.form.get("initial") or 0)
        flash("Caja abierta.", "ok")
    except Exception as e:  # noqa: BLE001
        flash(str(getattr(e, "description", e)), "error")
    return redirect(url_for("admin.caja"))


@bp.route("/caja/movimiento", methods=["POST"])
@login_required
@permission_required("caja.operar")
def caja_movimiento():
    session = open_cash_session()
    if session is None:
        flash("Abra la caja primero.", "error")
        return redirect(url_for("admin.caja"))
    try:
        cash_movement(session["id"], request.form.get("type"),
                      request.form.get("concept") or "",
                      request.form.get("amount"), _uid())
        flash("Movimiento registrado.", "ok")
    except Exception as e:  # noqa: BLE001
        flash(str(getattr(e, "description", e)), "error")
    return redirect(url_for("admin.caja"))


@bp.route("/caja/cerrar", methods=["POST"])
@login_required
@permission_required("caja.cerrar")
def caja_cerrar():
    try:
        _sid, expected, diff = cash_close(_uid(), request.form.get("counted"),
                                          request.form.get("notes") or "")
        msg = f"Caja cerrada. Esperado {expected} — Contado {round2(request.form.get('counted'))} — Diferencia {diff}."
        flash(msg, "ok" if abs(diff) < 0.01 else "error")
    except Exception as e:  # noqa: BLE001
        flash(str(getattr(e, "description", e)), "error")
    return redirect(url_for("admin.caja"))


@bp.route("/caja/historial")
@login_required
def caja_historial():
    if not (can("caja.operar") or can("caja.cerrar")):
        abort(403)
    rows = query(
        "SELECT cs.*, uo.username AS user_open_name, uc.username AS user_close_name, "
        "(SELECT COALESCE(SUM(CASE WHEN type='ingreso' THEN amount ELSE -amount END),0) "
        " FROM cash_movements WHERE session_id=cs.id) AS movs "
        "FROM cash_sessions cs LEFT JOIN users uo ON uo.id=cs.user_open "
        "LEFT JOIN users uc ON uc.id=cs.user_close ORDER BY cs.id DESC LIMIT 100")
    return render_template("caja_historial.html", sesiones=rows)


# ---------------------------------------------------------------- GASTOS

@bp.route("/gastos", methods=["GET", "POST"])
@login_required
def gastos():
    if not (can("caja.operar") or can("caja.cerrar") or can("reportes.ganancias")):
        abort(403)
    if request.method == "POST":
        if not can("caja.operar"):
            abort(403)
        f = request.form
        try:
            amount = round2(f.get("amount"))
        except (TypeError, ValueError):
            abort(400, description="Importe inválido.")
        concept = (f.get("concept") or "").strip()
        if not concept or amount <= 0:
            flash("Concepto e importe son obligatorios.", "error")
            return redirect(url_for("admin.gastos"))
        from .db import begin, commit, rollback

        begin()
        try:
            eid = insert(
                "INSERT INTO expenses (datetime, concept, category, amount, method, user_id, from_cash) "
                "VALUES (?,?,?,?,?,?,?)",
                (now_iso(), concept, f.get("category") or "General", amount,
                 f.get("method") or "efectivo", _uid(),
                 1 if f.get("from_cash") else 0),
            )
            if f.get("from_cash"):
                session = open_cash_session()
                if session:
                    mid = insert(
                        "INSERT INTO cash_movements (session_id, datetime, type, concept, amount, user_id, ref_type, ref_id) "
                        "VALUES (?, ?, 'egreso', ?, ?, ?, 'expense', ?)",
                        (session["id"], now_iso(), f"Gasto: {concept}", amount, _uid(), eid))
                    execute("UPDATE expenses SET cash_movement_id=? WHERE id=?", (mid, eid))
            audit("gasto", "gasto", eid, {"concept": concept, "amount": amount})
            commit()
            flash("Gasto registrado.", "ok")
        except Exception:
            rollback()
            raise
        return redirect(url_for("admin.gastos"))
    rows = query(
        "SELECT e.*, u.username FROM expenses e LEFT JOIN users u ON u.id=e.user_id "
        "ORDER BY e.id DESC LIMIT 200")
    desde = request.args.get("desde") or now_date()[:7] + "-01"
    total = query(
        "SELECT COALESCE(SUM(amount),0) AS s FROM expenses "
        "WHERE substr(datetime,1,10) >= ?", (desde,), one=True)["s"]
    return render_template("gastos.html", gastos=rows, desde=desde, total=total)


# --------------------------------------------------------------- USUARIOS

@bp.route("/usuarios")
@login_required
@permission_required("usuarios.gestionar")
def usuarios():
    rows = query("SELECT id, username, full_name, role, active, created_at, perms FROM users")
    return render_template("usuarios.html", users=rows, all_perms=ALL_PERMS,
                           role_defaults={k: sorted(v) for k, v in ROLE_DEFAULTS.items()})


@bp.route("/usuarios/nuevo", methods=["GET", "POST"])
@login_required
@permission_required("usuarios.gestionar")
def usuario_nuevo():
    if request.method == "POST":
        f = request.form
        username = (f.get("username") or "").strip().lower()
        pw = f.get("password") or ""
        role = f.get("role") or "vendedor"
        if not username or len(pw) < 8:
            flash("Usuario y contraseña (mínimo 8 caracteres) son obligatorios.", "error")
            return redirect(url_for("admin.usuario_nuevo"))
        if role not in ROLE_DEFAULTS:
            flash("Rol inválido.", "error")
            return redirect(url_for("admin.usuario_nuevo"))
        if query("SELECT id FROM users WHERE username=?", (username,), one=True):
            flash("El usuario ya existe.", "error")
            return redirect(url_for("admin.usuario_nuevo"))
        uid = insert(
            "INSERT INTO users (username, password_hash, full_name, role, perms, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (username, hash_password(pw), (f.get("full_name") or "").strip(), role,
             json.dumps(_perms_from_form(f)), now_iso()),
        )
        audit("crear", "usuario", uid, {"username": username, "role": role})
        flash("Usuario creado.", "ok")
        return redirect(url_for("admin.usuarios"))
    defaults = {k: sorted(v) for k, v in ROLE_DEFAULTS.items()}
    return render_template("usuario_form.html", u=None, all_perms=ALL_PERMS,
                           role_defaults=defaults, effective=set(ROLE_DEFAULTS["vendedor"]))


def _perms_from_form(f) -> dict:
    out = {}
    for p in ALL_PERMS:
        key = f"perm_{p.replace('.', '_')}"
        out[p] = key in f
    return out


@bp.route("/usuarios/<int:uid>", methods=["GET", "POST"])
@login_required
@permission_required("usuarios.gestionar")
def usuario_detalle(uid):
    u = query("SELECT * FROM users WHERE id=?", (uid,), one=True)
    if u is None:
        abort(404)
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        if action == "eliminar":
            if uid == _uid():
                flash("No puede eliminar su propio usuario.", "error")
            else:
                execute("UPDATE users SET active=0 WHERE id=?", (uid,))
                audit("desactivar", "usuario", uid, {})
                flash("Usuario desactivado.", "ok")
            return redirect(url_for("admin.usuarios"))
        role = f.get("role") or u["role"]
        if role not in ROLE_DEFAULTS:
            abort(400, description="Rol inválido.")
        execute("UPDATE users SET full_name=?, role=?, perms=?, active=? WHERE id=?",
                ((f.get("full_name") or u["full_name"]).strip(), role,
                 json.dumps(_perms_from_form(f)), 1 if f.get("active") else 0, uid))
        if f.get("password"):
            if len(f["password"]) < 8:
                flash("La contraseña debe tener al menos 8 caracteres.", "error")
                return redirect(url_for("admin.usuario_detalle", uid=uid))
            execute("UPDATE users SET password_hash=? WHERE id=?",
                    (hash_password(f["password"]), uid))
        audit("modificar", "usuario", uid, {"role": role})
        flash("Usuario actualizado.", "ok")
        return redirect(url_for("admin.usuario_detalle", uid=uid))
    from .security import user_perms as _up
    defaults = {k: sorted(v) for k, v in ROLE_DEFAULTS.items()}
    return render_template("usuario_form.html", u=u, all_perms=ALL_PERMS,
                           role_defaults=defaults, effective=_up(u))


# ---------------------------------------------------------- CONFIGURACIÓN

@bp.route("/configuracion")
@login_required
@permission_required("configuracion.gestionar")
def configuracion():
    settings = {r["key"]: r["value"] for r in query("SELECT * FROM settings")}
    tab = request.args.get("tab") or "negocio"
    taxes = query(
        "SELECT t.*, c.name AS cat_name, p.description AS prod_desc FROM taxes t "
        "LEFT JOIN categories c ON c.id=t.category_id "
        "LEFT JOIN products p ON p.id=t.product_id ORDER BY t.id DESC")
    cats = query("SELECT * FROM categories ORDER BY name")
    units = query("SELECT * FROM units ORDER BY name")
    accounts = query("SELECT * FROM transfer_accounts ORDER BY bank")
    payment_methods = json.loads(settings.get("payment_methods", "[]")) or [
        "efectivo", "transferencia", "debito", "credito", "cuenta_corriente"]
    return render_template("configuracion.html", settings=settings, tab=tab, taxes=taxes,
                           cats=cats, units=units, accounts=accounts,
                           all_perms=ALL_PERMS, payment_methods=payment_methods)


@bp.route("/configuracion/negocio", methods=["POST"])
@login_required
@permission_required("configuracion.gestionar")
def config_negocio():
    f = request.form
    keys = ("business_name", "business_address", "business_cuit", "business_iva",
            "ticket_footer", "fiscal_note", "currency")
    changes = {}
    for k in keys:
        if k in f:
            old = query("SELECT value FROM settings WHERE key=?", (k,), one=True)
            old_v = old["value"] if old else ""
            if old_v != f[k]:
                changes[k] = {"old": old_v, "new": f[k]}
                execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, f[k]))
    if "logo_data" in f and f.get("logo_data"):
        execute("INSERT INTO settings (key, value) VALUES ('logo', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (f["logo_data"],))
    audit("configurar", "negocio", None, changes or "sin cambios")
    flash("Configuración guardada.", "ok")
    return redirect(url_for("admin.configuracion", tab="negocio"))


# ------------------------------------------------------------ IMPUESTOS

@bp.route("/configuracion/impuestos", methods=["POST"])
@login_required
@permission_required("configuracion.gestionar")
def config_impuestos():
    f = request.form
    action = f.get("action")
    if action == "crear":
        name = (f.get("name") or "").strip()
        try:
            rate = float(f.get("rate") or 0)
        except ValueError:
            abort(400, description="Alícuota inválida.")
        if not name or rate < 0:
            abort(400, description="Nombre y alícuota (>= 0) son obligatorios.")
        tid = insert(
            "INSERT INTO taxes (name, rate, mode, scope, category_id, product_id, active, "
            "valid_from, valid_to, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (name, rate, f.get("mode") or "agregado", f.get("scope") or "global",
             int(f["category_id"]) if f.get("category_id") else None,
             int(f["product_id"]) if f.get("product_id") else None,
             1 if f.get("active") else 0,
             f.get("valid_from") or None, f.get("valid_to") or None,
             f.get("notes") or "", now_iso()),
        )
        execute("INSERT INTO tax_audit (tax_id, action, new_json, user_id, datetime) "
                "VALUES (?,?,?,?,?)",
                (tid, "crear", json.dumps(dict(name=name, rate=rate,
                                               mode=f.get("mode"), scope=f.get("scope"),
                                               active=bool(f.get("active"))),
                                          ensure_ascii=False), _uid(), now_iso()))
        audit("crear", "impuesto", tid, {"name": name, "rate": rate})
        flash(f"Impuesto '{name}' creado. "
              + ("Activo." if f.get("active") else "Inactivo (no se aplicará)."), "ok")
    elif action == "editar" or action == "activar" or action == "desactivar":
        tid = int(f.get("tax_id"))
        old = query("SELECT * FROM taxes WHERE id=?", (tid,), one=True)
        if old is None:
            abort(404)
        active = old["active"]
        if action == "activar":
            active = 1
        elif action == "desactivar":
            active = 0
        elif f.get("active") is not None:
            active = 1 if f.get("active") else 0
        name = (f.get("name") or old["name"]).strip()
        try:
            rate = float(f.get("rate", old["rate"]))
        except ValueError:
            rate = old["rate"]
        execute(
            "UPDATE taxes SET name=?, rate=?, mode=?, scope=?, active=?, valid_from=?, "
            "valid_to=?, notes=? WHERE id=?",
            (name, rate, f.get("mode") or old["mode"], f.get("scope") or old["scope"],
             active, f.get("valid_from", old["valid_from"]),
             f.get("valid_to", old["valid_to"]), f.get("notes", old["notes"]), tid))
        new = dict(name=name, rate=rate, mode=f.get("mode") or old["mode"],
                   scope=f.get("scope") or old["scope"], active=bool(active))
        execute("INSERT INTO tax_audit (tax_id, action, old_json, new_json, user_id, datetime) "
                "VALUES (?,?,?,?,?,?)",
                (tid, "modificar", json.dumps(dict(old), ensure_ascii=False, default=str),
                 json.dumps(new, ensure_ascii=False), _uid(), now_iso()))
        audit("modificar", "impuesto", tid, {"old": {"active": old["active"], "rate": old["rate"]},
                                             "new": new})
        flash("Impuesto actualizado. Las ventas históricas conservan sus importes originales.", "ok")
    elif action == "historial":
        pass
    return redirect(url_for("admin.configuracion", tab="impuestos"))


@bp.route("/configuracion/impuestos/<int:tid>/historial")
@login_required
@permission_required("configuracion.gestionar")
def impuesto_historial(tid):
    rows = query("SELECT * FROM tax_audit WHERE tax_id=? ORDER BY id DESC", (tid,))
    return render_template("impuesto_historial.html", rows=rows, tid=tid)


# ------------------------------------------- CATEGORÍAS / UNIDADES / CTAS.

@bp.route("/configuracion/categorias", methods=["POST"])
@login_required
@permission_required("configuracion.gestionar")
def config_categorias():
    name = (request.form.get("name") or "").strip()
    if name:
        execute("INSERT INTO categories (name) VALUES (?)", (name,))
        audit("crear", "categoria", None, {"name": name})
        flash("Categoría creada.", "ok")
    return redirect(url_for("admin.configuracion", tab="categorias"))


@bp.route("/configuracion/unidades", methods=["POST"])
@login_required
@permission_required("configuracion.gestionar")
def config_unidades():
    name = (request.form.get("name") or "").strip().lower()
    if name:
        execute("INSERT OR IGNORE INTO units (name) VALUES (?)", (name,))
        audit("crear", "unidad", None, {"name": name})
        flash("Unidad creada.", "ok")
    return redirect(url_for("admin.configuracion", tab="unidades"))


@bp.route("/configuracion/cuentas-transferencia", methods=["POST"])
@login_required
@permission_required("configuracion.gestionar")
def config_cuentas():
    f = request.form
    action = f.get("action")
    if action == "crear":
        if not (f.get("bank") or "").strip():
            flash("Indique el banco/entidad.", "error")
        else:
            insert("INSERT INTO transfer_accounts (bank, alias, cbu, holder) VALUES (?,?,?,?)",
                   (f["bank"].strip(), f.get("alias", "").strip(), f.get("cbu", "").strip(),
                    f.get("holder", "").strip()))
            audit("crear", "cuenta_transferencia", None, {"bank": f["bank"]})
            flash("Cuenta destino de transferencias agregada.", "ok")
    elif action == "toggle":
        execute("UPDATE transfer_accounts SET active = 1 - active WHERE id=?",
                (int(f.get("id")),))
    return redirect(url_for("admin.configuracion", tab="transferencias"))


@bp.route("/configuracion/metodos-pago", methods=["POST"])
@login_required
@permission_required("configuracion.gestionar")
def config_metodos():
    activos = request.form.getlist("method")
    validos = {"efectivo", "transferencia", "debito", "credito", "cuenta_corriente"}
    activos = [m for m in activos if m in validos]
    execute("INSERT INTO settings (key, value) VALUES ('payment_methods', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(activos),))
    audit("configurar", "metodos_pago", None, activos)
    flash("Medios de pago actualizados.", "ok")
    return redirect(url_for("admin.configuracion", tab="medios"))


# ----------------------------------------------------------- LICENCIAS

@bp.route("/licencias", methods=["GET", "POST"])
@login_required
def licencias():
    if not (can("licencias.gestionar") or can("configuracion.gestionar")):
        abort(403)
    if request.method == "POST":
        blob = (request.form.get("payload") or "").strip()
        ok, msg = lic.import_license(blob)
        audit("importar_licencia", "licencia", None, {"ok": ok, "msg": msg})
        flash(msg, "ok" if ok else "error")
        return redirect(url_for("admin.licencias"))
    state = lic.load_state()
    row = query("SELECT * FROM license_info WHERE id=1", one=True)
    return render_template("licencias.html", state=state, row=row)


@bp.route("/licencias/exportar")
@login_required
def licencias_exportar():
    """Exportación de datos del comercio — permitida incluso con licencia suspendida."""
    if not (can("licencias.gestionar") or can("configuracion.gestionar")
            or can("reportes.ganancias")):
        abort(403)
    from .services import backup_json

    audit("exportar", "backup", None, {})
    return send_file(
        __import__("io").BytesIO(backup_json().encode("utf-8")),
        mimetype="application/json", as_attachment=True,
        download_name=f"ferregest_backup_{now_date()}.json")


# ----------------------------------------------------------- AUDITORÍA

@bp.route("/auditoria")
@login_required
@permission_required("auditoria.consultar")
def auditoria():
    q = (request.args.get("q") or "").strip()
    entidad = request.args.get("entidad") or ""
    sql = "SELECT * FROM audit_log WHERE 1=1"
    args = []
    if q:
        sql += " AND (username LIKE ? OR action LIKE ? OR entity LIKE ? OR detail LIKE ?)"
        like = f"%{q}%"
        args += [like, like, like, like]
    if entidad:
        sql += " AND entity=?"
        args.append(entidad)
    sql += " ORDER BY id DESC LIMIT 300"
    rows = query(sql, args)
    entidades = [r["entity"] for r in query("SELECT DISTINCT entity FROM audit_log ORDER BY entity")]
    return render_template("auditoria.html", rows=rows, q=q, entidad=entidad,
                           entidades=entidades)
