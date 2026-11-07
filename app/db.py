"""FerreGest AR — utilidades de persistencia (SQLite).

Cambios de auditoría aplicados aquí:

- **ARQ-02**: la ruta de la base se toma de ``app.config['FERREGEST_DB']``
  cuando existe contexto de aplicación. ``create_app()`` ya no modifica
  ``os.environ``, de modo que dos instancias pueden usar dos bases distintas en
  el mismo proceso.
- **ARQ-11**: las migraciones se aplican **una transacción por archivo**
  (``BEGIN IMMEDIATE`` ... ``COMMIT``), serializadas entre procesos, con copia
  de seguridad previa del archivo y rollback automático ante cualquier error.
  Una migración fallida deja el esquema exactamente como estaba.
- **ARQ-12**: se configura ``busy_timeout`` explícito y ``synchronous=NORMAL``
  bajo WAL, y se documenta el límite real de concurrencia en
  ``docs/ARQUITECTURA.md``.
- **ARQ-09**: ``round2`` usa aritmética decimal con redondeo HALF_UP.
"""
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import current_app, g, has_app_context

from . import config as cfg
from .money import D, f2, q2, q4

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(BASE_DIR, "migrations")
BACKUP_DIR = os.path.join(BASE_DIR, "var", "migration-backups")


def now_iso() -> str:
    """Fecha/hora local de Argentina en formato ISO."""
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def now_date() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def minutes_ago(minutes: int) -> str:
    return (datetime.now(TZ) - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def round2(x) -> float:
    """Importe monetario a 2 decimales (redondeo comercial HALF_UP).

    Devuelve ``float`` porque la columna SQLite es ``REAL``, pero el valor ya
    está cuantizado, de modo que no acumula error binario (ARQ-09).
    """
    return f2(x)


def round4(x) -> float:
    """Cantidad a 4 decimales (stock, metros, kilos)."""
    return float(q4(x))


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        path = current_db_path()
        # isolation_level=None => autocommit por defecto; las transacciones se
        # abren explícitamente con begin() para agrupar operaciones de negocio.
        g.db = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES,
                               isolation_level=None)
        g.db.row_factory = sqlite3.Row
        # ARQ-12: esperar antes de fallar con "database is locked".
        g.db.execute(f"PRAGMA busy_timeout = {int(cfg.BUSY_TIMEOUT_MS)}")
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA synchronous = NORMAL")
    return g.db


def begin():
    """Abre una transacción explícita (los execute() posteriores no commitean)."""
    if not g.get("in_txn"):
        get_db().execute("BEGIN")
        g.in_txn = True


def begin_immediate():
    """Como :func:`begin` pero toma el lock de escritura de inmediato.

    Recomendado para operaciones de negocio que leen y luego escriben (ventas,
    compras, caja): evita ``SQLITE_BUSY`` por upgrade de lock bajo concurrencia.
    """
    if not g.get("in_txn"):
        get_db().execute("BEGIN IMMEDIATE")
        g.in_txn = True


def commit():
    if g.get("in_txn"):
        get_db().commit()
        g.in_txn = False


def rollback():
    if g.get("in_txn"):
        try:
            get_db().rollback()
        finally:
            g.in_txn = False


def current_db_path() -> str:
    """Ruta de la base: configuración de la app > variable de entorno > default.

    ARQ-02: con contexto de aplicación se usa ``app.config``; sólo fuera de la
    app (CLI, herramientas) se recurre al entorno.
    """
    if has_app_context():
        path = current_app.config.get("FERREGEST_DB")
        if path:
            return path
    return cfg.resolve_db_path()


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, timeout=cfg.BUSY_TIMEOUT_MS / 1000)
    conn.execute(f"PRAGMA busy_timeout = {int(cfg.BUSY_TIMEOUT_MS)}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    """Ejecuta una sentencia. Si hay transacción abierta (begin), no commitea."""
    db = get_db()
    cur = db.execute(sql, args)
    if not g.get("in_txn"):
        db.commit()
    return cur.lastrowid


def insert(sql, args=()):
    """Inserta sin commit inmediato (útil dentro de transacciones de servicio)."""
    return get_db().execute(sql, args).lastrowid


def iter_statements(script: str):
    """Divide un script SQL en sentencias completas sin romper triggers.

    Usa ``sqlite3.complete_statement``, que entiende los bloques
    ``CREATE TRIGGER ... BEGIN ... END;`` (un ``split(';')`` ingenuo los corta).
    """
    buffer = ""
    for line in script.splitlines(keepends=True):
        if line.lstrip().startswith("--"):
            # Los comentarios se descartan: si quedaran pegados al principio del
            # buffer, la sentencia siguiente parecería un comentario y se perdería.
            continue
        buffer += line
        if sqlite3.complete_statement(buffer):
            stmt = buffer.strip()
            buffer = ""
            if stmt and not stmt.startswith("--"):
                yield stmt
    tail = buffer.strip()
    if tail:
        yield tail


def _pre_migration_backup(db_path: str):
    """Copia de seguridad del archivo antes de migrar (sólo si la base existe)."""
    if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"pre-migracion-{stamp}.db")
    shutil.copy2(db_path, dest)
    for suffix in ("-wal", "-shm"):
        src = db_path + suffix
        if os.path.exists(src):
            shutil.copy2(src, dest + suffix)
    return dest


def migrate(db_path: str | None = None, backup: bool = True) -> list[str]:
    """Aplica las migraciones pendientes de ``migrations/*.sql`` en orden.

    ARQ-11: cada archivo se aplica dentro de ``BEGIN IMMEDIATE`` ... ``COMMIT``.
    Si algo falla se hace ``ROLLBACK`` y se re-lanza el error: el archivo queda
    con el esquema anterior y la migración no se marca como aplicada. Antes de
    empezar se copia la base a ``var/migration-backups/``.

    Devuelve la lista de migraciones aplicadas en esta corrida.
    """
    if db_path is None:
        db_path = current_db_path()
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    applied_now: list[str] = []
    pending = _pending_migrations(db_path)
    if not pending:
        return applied_now

    if backup:
        try:
            _pre_migration_backup(db_path)
        except OSError:
            pass  # la copia es una red de seguridad, no debe impedir migrar

    conn = _connect(db_path)
    try:
        for fname in pending:
            with open(os.path.join(MIGRATIONS_DIR, fname), encoding="utf-8") as fh:
                sql = fh.read()
            try:
                conn.execute("BEGIN IMMEDIATE")
                for stmt in iter_statements(sql):
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                    (fname, now_iso()),
                )
                conn.execute("COMMIT")
            except Exception as exc:  # rollback y se propaga con contexto
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise RuntimeError(
                    f"La migración {fname} falló y se revirtió por completo "
                    f"(la base quedó como estaba). Detalle: {exc}"
                ) from exc
            applied_now.append(fname)
    finally:
        conn.close()
    return applied_now


def _pending_migrations(db_path: str) -> list[str]:
    conn = _connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name TEXT PRIMARY KEY, applied_at TEXT)"
        )
        applied = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    finally:
        conn.close()
    files = sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql"))
    return [f for f in files if f not in applied]


def applied_migrations(db_path: str | None = None) -> list[str]:
    if db_path is None:
        db_path = current_db_path()
    if not os.path.exists(db_path):
        return []
    conn = _connect(db_path)
    try:
        return [r[0] for r in conn.execute(
            "SELECT name FROM schema_migrations ORDER BY name")]
    finally:
        conn.close()


def db_exists() -> bool:
    return os.path.exists(current_db_path())


def table_exists(name: str) -> bool:
    """True si la tabla existe (evita romper si una migración no se aplicó)."""
    row = query(
        "SELECT 1 AS ok FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,), one=True)
    return row is not None
