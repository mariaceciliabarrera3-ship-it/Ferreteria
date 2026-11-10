"""FerreGest AR — configuración centralizada (ARQ-02 y ARQ-04).

Centraliza dos decisiones que antes estaban repartidas entre ``os.environ`` y
comentarios del código:

1. **Ruta de la base de datos** (ARQ-02): pertenece a la *instancia* de Flask
   (``app.config['FERREGEST_DB']``). ``create_app()`` ya no toca variables de
   entorno globales, así que dos apps pueden convivir en el mismo proceso con
   dos bases distintas. Fuera de una app (CLI, ``seed_demo.py``, ``tools/``) se
   sigue usando ``FERREGEST_DB`` como respaldo.

2. **Modo de ejecución** (ARQ-04): ``FERREGEST_MODE`` = ``demo`` | ``production``.
   En ``production`` una licencia ausente, inválida, vencida fuera de gracia o
   suspendida **bloquea las operaciones comerciales** (fail-safe). En ``demo``
   se permite operar con datos ficticios y aviso permanente.
"""
import os

DEMO = "demo"
PRODUCTION = "production"
VALID_MODES = (DEMO, PRODUCTION)

#: Umbral de intentos fallidos de login (ARQ-08)
LOGIN_MAX_ATTEMPTS = int(os.environ.get("FERREGEST_LOGIN_MAX_ATTEMPTS", "8"))
#: Ventana de bloqueo tras superar el umbral, en minutos (ARQ-08)
LOGIN_LOCKOUT_MINUTES = int(os.environ.get("FERREGEST_LOGIN_LOCKOUT_MINUTES", "15"))
#: Ventana en la que se cuentan los intentos fallidos, en minutos (ARQ-08)
LOGIN_WINDOW_MINUTES = int(os.environ.get("FERREGEST_LOGIN_WINDOW_MINUTES", "60"))
#: Timeout de espera cuando otro proceso está escribiendo en SQLite (ARQ-12)
BUSY_TIMEOUT_MS = int(os.environ.get("FERREGEST_BUSY_TIMEOUT_MS", "8000"))
#: Duración de la sesión (ARQ-15)
SESSION_HOURS = float(os.environ.get("FERREGEST_SESSION_HOURS", "8"))


def mode() -> str:
    """Modo de ejecución declarado. Por defecto ``demo`` (nunca producción por
    omisión: si alguien se olvida la variable, el sistema no bloquea a la
    ferretería, pero tampoco finge estar licenciado)."""
    m = (os.environ.get("FERREGEST_MODE", "") or "").strip().lower()
    return m if m in VALID_MODES else DEMO


def is_production() -> bool:
    """¿La instalación exige licencia válida para operar?"""
    return mode() == PRODUCTION


def require_license() -> bool:
    """¿Esta instalación exige licencia válida? (predeterminado: sí).

    ``FERREGEST_REQUIRE_LICENSE=0`` desactiva el control de licencias por
    completo: no hay bloqueo de operaciones ni cartel en pantalla, en
    cualquier modo. Pensado para una copia de trabajo/desarrollo propia,
    sin modelo de licenciamiento.

    Con ``1`` (o sin definir la variable) se conserva el comportamiento
    auditado ARQ-04: producción sin licencia válida = operaciones
    comerciales bloqueadas. Ese es el default, así que una copia que se
    baje el repo sin configurar nada sigue teniendo el candado puesto.
    """
    return (os.environ.get("FERREGEST_REQUIRE_LICENSE", "1") or "1").strip() != "0"


def setup_wizard() -> bool:
    """¿Esta instalación debe pedirle a la dueña que cree su propio usuario
    administrador en el primer arranque, en vez de crear uno automático?

    ``FERREGEST_SETUP_WIZARD=1`` activa la pantalla de configuración inicial
    (nombre, usuario y contraseña a elección) y evita el usuario ``admin``
    con clave generada o ``admin123``. Pensado para la copia que recibe un
    comercio, no para desarrollo ni para las pruebas automatizadas (que
    siguen usando ``admin``/``admin123`` como hasta ahora).

    Por defecto está apagado (``0``), así que nada de lo existente cambia
    si no se define esta variable.
    """
    return (os.environ.get("FERREGEST_SETUP_WIZARD", "0") or "0").strip() == "1"


def default_db_path() -> str:
    """Ruta por defecto de la base (junto al paquete ``app``)."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "ferregest.db")


def resolve_db_path(db_path: str | None = None) -> str:
    """Resuelve la ruta de la base: explícita > variable de entorno > default."""
    path = db_path or os.environ.get("FERREGEST_DB") or default_db_path()
    return os.path.abspath(os.path.expanduser(path))


def bind_host() -> str:
    """Host de escucha. En local, 127.0.0.1 (no exponer en la red sin decirlo)."""
    return os.environ.get("FERREGEST_HOST", "127.0.0.1")
