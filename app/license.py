"""FerreGest AR — sistema de licenciamiento (instalaciones independientes).

Modelo:
- Cada instalación tiene un install_id propio y una licencia firmada
  criptográficamente (HMAC-SHA256) emitida por el panel central de la
  propietaria del producto (tools/panel_licencias.py).
- La verificación es 100% local: NO envía información comercial del comercio
  (ni ventas, clientes, ni movimientos) a ningún servidor. El payload solo
  contiene datos de licencia.
- Estados: activa → por_vencer (aviso previo) → vencida (período de gracia
  configurable) → suspendida (bloquea operaciones comerciales, conserva y
  permite exportar los datos) → reactivada al firmar una licencia nueva.
- La suspensión jamás borra ni destruye datos: solo se bloquean escrituras
  comerciales (ventas, compras, caja, stock). Lectura, informes y exportación
  siguen disponibles.

Cambios de auditoría aplicados aquí:

- **ARQ-03**: se separaron *lectura* y *escritura*. :func:`get_state` **no
  toca la base de datos** (ni ``last_check`` ni nada) y es la única función que
  usa el ``context_processor`` de plantillas. El registro del chequeo queda en
  :func:`record_check`, invocado en el arranque y al importar una licencia.
  Antes, renderizar cualquier página generaba un ``UPDATE`` en SQLite.
- **ARQ-04**: el modo de ejecución decide qué pasa sin licencia válida.
  ``FERREGEST_MODE=demo`` (por defecto) permite operar con datos ficticios y
  aviso permanente; ``FERREGEST_MODE=production`` bloquea las operaciones
  comerciales (fail-safe) si la licencia falta, es inválida, está vencida fuera
  de gracia o suspendida.
"""
import base64
import hashlib
import hmac
import json
import os
from datetime import date, datetime, timedelta

from . import config as cfg
from .db import execute, now_iso, query, round2

PAYLOAD_FIELDS = (
    "license_id",
    "install_id",
    "client",
    "issued_at",
    "expires_at",
    "grace_days",
    "warn_days",
    "status",
)


def _signing_key() -> bytes:
    k = os.environ.get("LICENSE_SIGNING_KEY", "").strip()
    if not k:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".license_key"
        )
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                k = fh.read().strip()
        elif os.environ.get("LICENSE_KEY_FALLBACK_DEV") == "1":
            k = "ferregest-dev-key"
        else:
            k = ""
    return k.encode("utf-8")


def signing_key_configured() -> bool:
    """¿Hay clave de firma disponible en esta instalación?

    En producción, sin clave de firma ninguna licencia puede verificarse, por lo
    que el sistema debe avisarlo y bloquear operaciones en lugar de asumir que
    "todo está bien" (ARQ-04).
    """
    return bool(_signing_key())


def sign_license(payload: dict) -> str:
    """Firma un payload de licencia. Función compartida con el panel central."""
    key = _signing_key()
    if not key:
        raise RuntimeError(
            "No hay clave de firma de licencias (variable LICENSE_SIGNING_KEY)."
        )
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    sig = hmac.new(key, data.encode("utf-8"), hashlib.sha256).hexdigest()
    blob = base64.urlsafe_b64encode(json.dumps({"p": payload, "s": sig}).encode()).decode()
    return blob


def verify_license(blob: str) -> dict | None:
    """Devuelve el payload si la firma es válida, o None."""
    key = _signing_key()
    if not key or not blob:
        return None
    try:
        raw = json.loads(base64.urlsafe_b64decode(blob.encode()))
        payload, sig = raw["p"], raw["s"]
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        expect = hmac.new(key, data.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return None
        for f in PAYLOAD_FIELDS:
            if f not in payload:
                return None
        return payload
    except Exception:
        return None


def get_install_id(create: bool = False) -> str:
    """Devuelve el install_id de la instalación.

    ARQ-03: por defecto **sólo lee**. Pasar ``create=True`` para generarlo (lo
    hace el bootstrap del primer arranque, nunca el renderizado de una página).
    """
    row = query("SELECT install_id FROM license_info WHERE id = 1", one=True)
    if row and row["install_id"]:
        return row["install_id"]
    if not create:
        return ""
    new_id = "FER-" + hashlib.sha256(os.urandom(16)).hexdigest()[:12].upper()
    if row is None:
        execute(
            "INSERT INTO license_info (id, install_id, updated_at) VALUES (1, ?, ?)",
            (new_id, now_iso()),
        )
    else:
        execute("UPDATE license_info SET install_id = ? WHERE id = 1", (new_id,))
    return new_id


def _base_state() -> dict:
    """Estado por defecto, sin escribir nada en la base (ARQ-03)."""
    return {
        "install_id": get_install_id(create=False),
        "license_id": "",
        "client": "",
        "status": "inactiva",
        "days_left": None,
        "expires_at": None,
        "grace_days": 7,
        "warn_days": 15,
        "message": "Instalación sin licencia activa. Contacte a la proveedora del sistema.",
        # ARQ-04: en demo se permite operar con datos ficticios; en producción no.
        "ops_allowed": not cfg.is_production(),
        "suspended": False,
        "banner": "",
        "mode": cfg.mode(),
        "last_check": None,
    }


def _free_state() -> dict:
    """Estado de una instalación sin control de licencias
    (``FERREGEST_REQUIRE_LICENSE=0``).

    Habilita todas las operaciones, no muestra cartel y no lee ni escribe
    la tabla ``license_info`` para decidir nada: la única fuente de verdad
    es la variable de entorno. Así una copia de trabajo propia arranca sin
    emitir ni importar licencias, y el resto del código no cambia.
    """
    state = _base_state()
    state["status"] = "libre"
    state["ops_allowed"] = True
    state["suspended"] = False
    state["banner"] = ""
    state["message"] = ("Control de licencias desactivado en esta instalación "
                         "(FERREGEST_REQUIRE_LICENSE=0): todas las operaciones "
                         "están habilitadas.")
    return state


def get_state() -> dict:
    """Estado de licencia **sin ningún efecto secundario** (ARQ-03).

    Sólo lee. Es la función que usan las plantillas, el panel y
    ``assert_ops_allowed()``. Para dejar registrado el momento del chequeo,
    llamar explícitamente a :func:`record_check`.
    """
    if not cfg.require_license():
        return _free_state()
    row = query("SELECT * FROM license_info WHERE id = 1", one=True)
    today = date.today()
    state = _base_state()
    if row is None:
        state["mode"] = cfg.mode()
        if cfg.is_production():
            _block_for_production(state, "sin_licencia",
                                  "MODO PRODUCCIÓN sin licencia cargada: las operaciones "
                                  "comerciales están bloqueadas. Importe una licencia válida "
                                  "en Administración → Licencia.")
        else:
            state["banner"] = (" MODO DEMO — sin licencia cargada: puede probar con datos "
                               "ficticios. No apto para uso comercial.")
        return state

    state["install_id"] = row["install_id"] or state["install_id"]
    state["grace_days"] = row["grace_days"] or 7
    state["warn_days"] = row["warn_days"] or 15
    state["last_check"] = row["last_check"]
    payload = verify_license(row["payload"]) if row["payload"] else None

    if payload is None:
        if cfg.is_production():
            detail = ("inválida o manipulada" if row["payload"] else "ausente")
            _block_for_production(state, "sin_licencia" if not row["payload"] else "invalida",
                                  f"MODO PRODUCCIÓN con licencia {detail}: las operaciones "
                                  "comerciales están bloqueadas. Sus datos están intactos y "
                                  "puede exportarlos o respaldarlos.")
        else:
            state["status"] = "invalida" if row["payload"] else "inactiva"
            state["message"] = ("Licencia inválida o manipulada (modo demo: puede seguir "
                                "probando con datos ficticios)." if row["payload"]
                                else "Instalación sin licencia activa (modo demo).")
            state["banner"] = (" MODO DEMO — " + ("licencia inválida." if row["payload"]
                                                  else "sin licencia cargada."))
        return state

    state["license_id"] = payload["license_id"]
    state["client"] = payload.get("client", "")
    state["expires_at"] = payload["expires_at"]
    state["grace_days"] = int(payload.get("grace_days", state["grace_days"]))
    state["warn_days"] = int(payload.get("warn_days", state["warn_days"]))
    try:
        exp = datetime.strptime(payload["expires_at"][:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        _block_for_production(state, "invalida",
                              "La licencia tiene una fecha de vencimiento ilegible.")
        state["status"] = "invalida"
        return state
    days_left = (exp - today).days
    state["days_left"] = days_left
    # Con una licencia verificada y vigente se habilitan las operaciones
    # (incluso en modo producción). Los bloqueos se aplican más abajo.
    state["ops_allowed"] = True

    if row["suspended"]:
        state["status"] = "suspendida"
        state["suspended"] = True
        state["ops_allowed"] = False
        state["message"] = (
            "Licencia SUSPENDIDA por falta de renovación. Sus datos están intactos: "
            "puede consultar, exportar y realizar copias de seguridad. "
            "Reactive la licencia para retomar las operaciones comerciales."
        )
        state["banner"] = " LICENCIA SUSPENDIDA — operaciones comerciales bloqueadas."
    elif days_left < 0:
        in_grace = (-days_left) <= state["grace_days"]
        if in_grace:
            state["status"] = "vencida_gracia"
            state["message"] = (
                f"La licencia venció el {exp.isoformat()} y está en el período de gracia "
                f"({state['grace_days']} días). Renueve para evitar la suspensión."
            )
            state["banner"] = f" LICENCIA VENCIDA — período de gracia: quedan {state['grace_days'] + days_left} día(s)."
        else:
            state["status"] = "suspendida"
            state["suspended"] = True
            state["ops_allowed"] = False
            state["message"] = (
                "La licencia venció y terminó el período de gracia: operaciones "
                "comerciales suspendidas. Sus datos siguen completos y exportables."
            )
            state["banner"] = " LICENCIA VENCIDA — operaciones comerciales suspendidas."
    elif days_left <= state["warn_days"]:
        state["status"] = "por_vencer"
        state["message"] = f"Su licencia vence en {days_left} día(s): renueve a tiempo."
        state["banner"] = f" LICENCIA PRÓXIMA A VENCER — quedan {days_left} día(s)."
    else:
        state["status"] = "activa"
        state["message"] = f"Licencia activa. Vence el {exp.isoformat()}."
    return state


def _block_for_production(state: dict, status: str, message: str):
    """Aplica el bloqueo fail-safe de operaciones (ARQ-04)."""
    state["status"] = status
    state["ops_allowed"] = False
    state["suspended"] = True
    state["message"] = message
    state["banner"] = " LICENCIA NO VÁLIDA — operaciones comerciales bloqueadas (modo producción)."


def load_state(record: bool = False) -> dict:
    """Compatibilidad: devuelve el estado de licencia.

    ``record=True`` además registra el momento del chequeo (escritura explícita
    y deliberada). El valor por omisión es ``False``: **leer no escribe**
    (ARQ-03).
    """
    state = get_state()
    if record:
        record_check()
        state["last_check"] = now_iso()
    return state


def record_check() -> None:
    """Registra el instante del último chequeo de licencia (única escritura).

    Se invoca al arrancar la aplicación y al importar/actualizar una licencia,
    nunca desde el renderizado de plantillas (ARQ-03).
    """
    try:
        execute("UPDATE license_info SET last_check = ? WHERE id = 1", (now_iso(),))
    except Exception:
        # Registrar el chequeo es informativo: jamás debe romper una petición.
        pass


def import_license(blob: str) -> tuple[bool, str]:
    """Importa una licencia firmada (reacciona una licencia suspendida)."""
    payload = verify_license(blob.strip())
    if payload is None:
        return False, "La licencia no es válida (firma incorrecta o archivo corrupto)."
    install = get_install_id(create=True)
    if payload["install_id"] != install:
        return False, (
            f"La licencia pertenece a otra instalación ({payload['install_id']}) "
            f"y no a esta ({install})."
        )
    execute(
        "UPDATE license_info SET license_id=?, client=?, issued_at=?, expires_at=?, "
        "grace_days=?, warn_days=?, suspended=0, payload=?, updated_at=?, last_check=? WHERE id=1",
        (
            payload["license_id"],
            payload.get("client", ""),
            payload["issued_at"],
            payload["expires_at"],
            int(payload.get("grace_days", 7)),
            int(payload.get("warn_days", 15)),
            blob.strip(),
            now_iso(),
            now_iso(),
        ),
    )
    return True, f"Licencia {payload['license_id']} importada y activada."


def set_local_suspended(flag: int):
    """Suspensión local (para pruebas/consola del administrador de la instalación)."""
    execute(
        "UPDATE license_info SET suspended=?, updated_at=? WHERE id=1",
        (1 if flag else 0, now_iso()),
    )
