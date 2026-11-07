"""FerreGest AR — autenticación, roles, permisos, CSRF y auditoría.

Contraseñas: hash pbkdf2/scrypt de Werkzeug (nunca texto plano).
CSRF: token aleatorio por sesión validado en todo POST vía cabecera o campo _csrf.
"""
import functools
import json
import os
import secrets

from flask import (abort, g, has_app_context, has_request_context, redirect,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from . import config as cfg
from .db import execute, minutes_ago, now_iso, query, table_exists

# Claves de permiso (configurables por usuario desde la UI de Administración)
ALL_PERMS = [
    "pos.operar",
    "productos.gestionar",
    "precios.modificar",
    "descuentos.aplicar",
    "ventas.anular",
    "stock.modificar",
    "stock.negativo",
    "compras.gestionar",
    "caja.operar",
    "caja.cerrar",
    "transferencias.verificar",
    "clientes.gestionar",
    "cuentas.consultar",
    "compras.consultar",
    "reportes.ganancias",
    "configuracion.gestionar",
    "usuarios.gestionar",
    "licencias.gestionar",
    "auditoria.consultar",
]

# Permisos por defecto de cada rol (el administrador puede ajustarlos por usuario)
ROLE_DEFAULTS = {
    "administrador": set(ALL_PERMS),
    "vendedor": {
        "pos.operar",
        "clientes.gestionar",
        "cuentas.consultar",
        "caja.operar",
        "descuentos.aplicar",
        "compras.consultar",
    },
    "stock": {
        "productos.gestionar",
        "stock.modificar",
        "compras.gestionar",
        "compras.consultar",
    },
    "administrativo": {
        "compras.gestionar",
        "compras.consultar",
        "clientes.gestionar",
        "cuentas.consultar",
        "caja.operar",
        "caja.cerrar",
        "reportes.ganancias",
        "transferencias.verificar",
        "productos.gestionar",
        "precios.modificar",
    },
}


def hash_password(pw: str) -> str:
    return generate_password_hash(pw)


def verify_password(hashed: str, pw: str) -> bool:
    return check_password_hash(hashed, pw)


def user_perms(user_row) -> set:
    role = user_row["role"] if not isinstance(user_row, dict) else user_row.get("role", "")
    perms = set(ROLE_DEFAULTS.get(role, set()))
    raw = user_row["perms"] if not isinstance(user_row, dict) else user_row.get("perms", "{}")
    try:
        overrides = json.loads(raw or "{}")
    except (ValueError, TypeError):
        overrides = {}
    for k, v in overrides.items():
        if v:
            perms.add(k)
        else:
            perms.discard(k)
    return perms


def current_user():
    if "user" in g:
        return g.user
    g.user = None
    if not has_request_context():
        return None  # seed / CLI: sin request no hay sesión
    uid = session.get("user_id")
    if uid:
        row = query("SELECT * FROM users WHERE id = ? AND active = 1", (uid,), one=True)
        if row is None:
            session.clear()
        else:
            g.user = row
    return g.user


def can(perm: str) -> bool:
    u = current_user()
    if u is None:
        return False
    return perm in user_perms(u)


def login_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def permission_required(perm: str):
    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if current_user() is None:
                abort(401 if request.path.startswith("/api/") else 302)
            if not can(perm):
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def ensure_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def check_csrf():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    token = request.headers.get("X-CSRF-Token") or request.form.get("_csrf") or ""
    expected = session.get("csrf", "")
    if not expected or not token or not secrets.compare_digest(token, expected):
        abort(400, description="Token CSRF inválido o ausente.")


# ------------------------------------------------------- límite de intentos
# ARQ-08: el contador en memoria por proceso no servía multiworker y se perdía
# al reiniciar. Ahora los intentos fallidos se guardan en SQLite, así que el
# límite se comparte entre workers y sobrevive a los reinicios. Si la tabla no
# existe (base anterior a la migración 002) se usa un respaldo en memoria y se
# documenta la limitación.
_MEM_FAILED: dict[str, list[str]] = {}
LOGIN_TABLE = "login_attempts"


def _login_table_ready() -> bool:
    """True si se puede usar la tabla persistente (hay app y la tabla existe)."""
    if not has_app_context():
        return False
    try:
        return table_exists(LOGIN_TABLE)
    except Exception:
        return False


def register_login_failure(username: str) -> int:
    """Registra un intento fallido y devuelve el total vigente."""
    username = (username or "")[:64]
    if _login_table_ready():
        try:
            execute("DELETE FROM login_attempts WHERE at < ?", (minutes_ago(cfg.LOGIN_WINDOW_MINUTES),))
            execute(
                "INSERT INTO login_attempts (username, at, success) VALUES (?, ?, 0)",
                (username, now_iso()),
            )
            return login_failures(username)
        except Exception:
            pass
    now = now_iso()
    _MEM_FAILED.setdefault(username, []).append(now)
    cutoff = minutes_ago(cfg.LOGIN_WINDOW_MINUTES)
    _MEM_FAILED[username] = [t for t in _MEM_FAILED[username] if t >= cutoff]
    return len(_MEM_FAILED[username])


def login_failures(username: str) -> int:
    """Intentos fallidos del usuario dentro de la ventana vigente."""
    username = (username or "")[:64]
    if _login_table_ready():
        try:
            row = query(
                "SELECT COUNT(*) AS c FROM login_attempts WHERE username = ? "
                "AND success = 0 AND at >= ?",
                (username, minutes_ago(cfg.LOGIN_WINDOW_MINUTES)), one=True)
            if row is not None:
                return int(row["c"])
        except Exception:
            pass
    cutoff = minutes_ago(cfg.LOGIN_WINDOW_MINUTES)
    return len([t for t in _MEM_FAILED.get(username, []) if t >= cutoff])


def login_locked(username: str) -> bool:
    """True si el usuario superó el umbral y todavía está dentro del bloqueo."""
    if login_failures(username) < cfg.LOGIN_MAX_ATTEMPTS:
        return False
    if _login_table_ready():
        try:
            row = query(
                "SELECT MAX(at) AS last FROM login_attempts WHERE username = ? "
                "AND success = 0", (username,), one=True)
            if row and row["last"]:
                return row["last"] >= minutes_ago(cfg.LOGIN_LOCKOUT_MINUTES)
        except Exception:
            pass
    last = max(_MEM_FAILED.get(username, []) or [""])
    return bool(last) and last >= minutes_ago(cfg.LOGIN_LOCKOUT_MINUTES)


def clear_login_failures(username: str) -> None:
    """Limpia el contador tras un login correcto."""
    username = (username or "")[:64]
    if _login_table_ready():
        try:
            execute("DELETE FROM login_attempts WHERE username = ?", (username,))
        except Exception:
            pass
    _MEM_FAILED.pop(username, None)


def audit(action: str, entity: str, entity_id=None, detail: dict | str = ""):
    """Registra una acción importante en la bitácora (old/new en JSON)."""
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False, default=str)
    u = current_user()
    execute(
        "INSERT INTO audit_log (datetime, user_id, username, action, entity, entity_id, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            now_iso(),
            u["id"] if u else None,
            u["username"] if u else "sistema",
            action,
            entity,
            entity_id,
            detail[:4000],
        ),
    )


def secret_key() -> str:
    key = os.environ.get("FERREGEST_SECRET")
    if not key:
        # Se genera una vez y se guarda en el archivo de sesión/instalación.
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".secret")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                key = fh.read().strip()
        if not key:
            key = secrets.token_hex(32)
            umask = os.umask(0o077)
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(key)
            finally:
                os.umask(umask)
    return key
