# Ferreteria AR — Sistema de gestión integral para ferreterías (Argentina)

Software **real, funcional e instalable** de administración comercial para
ferreterías: punto de venta con cantidades fraccionadas y conversiones de
unidades, inventario auditado, compras y recepción de mercadería, caja con
arqueo, cuentas corrientes, transferencias bancarias con verificación manual,
impuestos configurables, usuarios con permisos granulares, licenciamiento por
instalación y exportación de datos.

- **Sin costos obligatorios**: Python + Flask + SQLite (todo libre y gratuito).
- **Una sola aplicación** instalable en la computadora del comercio.
- **Interfaz 100 % en español**, formato monetario argentino (`$ 1.234,56`).
- **Sin integraciones pagas**: no usa bancos, APIs de facturación ni IA.
- **Auditoría de arquitectura cerrada**: 16 hallazgos corregidos y probados
  (ver `docs/AUDITORIA_HALLAZGOS.md`).

> Subir el código a GitHub **no** significa desplegar la aplicación en Internet
> ni alojar la base de datos allí. FerreGest se ejecuta **localmente** en la
> computadora del comercio.

---

## Estado del proyecto

| Ítem | Estado |
|---|---|
| Pruebas automatizadas | **45/45 en verde** (`python3 -m pytest tests/ -v`) |
| Hallazgos críticos abiertos | **0** |
| Hallazgos altos abiertos | **0** |
| Hallazgos medios con mitigación documentada | 4 (ver `docs/AUDITORIA_HALLAZGOS.md`) |
| Control de secretos antes de commitear | `python3 tools/check_repo.py` → `CONTINUE` |

---

## Credenciales (importante)

**No hay contraseñas fijas en el repositorio.**

- En el **primer arranque** se crea el usuario `admin`:
  - si definió `FERREGEST_ADMIN_PASSWORD`, se usa esa clave;
  - en modo **producción**, si no la definió, se **genera una aleatoria** y se
    guarda en `var/clave_inicial_admin.txt` (permisos 0600);
  - en modo **demo**, si no la definió, se usa `admin123` **y se imprime un
    aviso**: cámbiela antes de cargar datos reales.
- El seed de demostración (`seed_demo.py`) **no contiene claves fijas**: las
  toma de variables de entorno o las genera aleatoriamente, y sólo funciona
  sobre una base declarada de demostración (ARQ-05).

Cambie la contraseña en **Mi cuenta → Cambiar contraseña** y cree un usuario
por empleado con permisos propios.

---

## Instalación (local)

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env        # complete FERREGEST_MODE, FERREGEST_DB y la clave de admin
python3 run.py              # http://127.0.0.1:8000
```

Datos ficticios de demostración **sólo en una base demo**:

```bash
FERREGEST_MODE=demo FERREGEST_DB=/ruta/demo.db python3 seed_demo.py --confirmar-demo
```

Guía completa paso a paso en **`docs/INSTALACION_LOCAL.md`**.

## Variables de entorno

| Variable | Defecto | Para qué |
|---|---|---|
| `FERREGEST_MODE` | `demo` | `production` exige licencia válida para operar (ARQ-04) |
| `FERREGEST_DB` | `./ferregest.db` | Ruta de la base SQLite de esta instalación |
| `FERREGEST_SECRET` | `.secret` (0600) | Secreto de firma de cookies de sesión |
| `FERREGEST_ADMIN_PASSWORD` | *(ver arriba)* | Clave del `admin` en el primer arranque |
| `SESSION_COOKIE_SECURE` | `0` | `1` cuando se sirve por HTTPS |
| `FERREGEST_HOST` | `127.0.0.1` | Interfaz de escucha (`0.0.0.0` sólo si se decide exponerla) |
| `FERREGEST_SESSION_HOURS` | `8` | Duración de la sesión (ARQ-15) |
| `FERREGEST_LOGIN_MAX_ATTEMPTS` | `8` | Intentos fallidos antes del bloqueo (ARQ-08) |
| `FERREGEST_LOGIN_WINDOW_MINUTES` | `60` | Ventana en la que se cuentan los intentos |
| `FERREGEST_LOGIN_LOCKOUT_MINUTES` | `15` | Duración del bloqueo |
| `FERREGEST_BUSY_TIMEOUT_MS` | `8000` | Espera cuando otro proceso está escribiendo (ARQ-12) |
| `PORT` | `8000` | Puerto del servidor local |
| `LICENSE_SIGNING_KEY` | — | **Sólo** en el entorno privado de emisión de licencias |

Plantilla comentada en **`.env.example`** (sin valores reales).

## Pruebas

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v        # 45 pruebas: 12 del pliego + 33 de auditoría
node tests/js/xss_harness.js       # arnés DOM anti-XSS (opcional, Node 18+)
python3 tools/check_repo.py        # control de secretos antes del commit
```

Las pruebas crean su propia base temporal (`tests/tmp_*.db`): **nunca** tocan
la base del comercio ni la de demostración.
Informe y evidencia: `docs/INFORME_PRUEBAS.md` y `docs/informe_pruebas_raw.txt`.

## Estructura

```text
ferregest/
├── app/
│   ├── __init__.py      # factory, filtros, cabeceras de seguridad, errores
│   ├── config.py        # modo, ruta de base, umbrales (ARQ-02/04)
│   ├── db.py            # SQLite + PRAGMAs + migraciones transaccionales
│   ├── money.py         # aritmética decimal y redondeo comercial (ARQ-09)
│   ├── security.py      # sesión, roles/permisos, CSRF, auditoría, login
│   ├── fiscal.py        # motor de impuestos y precios centralizado
│   ├── license.py       # licenciamiento local firmado (HMAC-SHA256)
│   ├── services.py      # ventas, stock, compras, caja, cuentas (transaccional)
│   ├── bp_*.py          # blueprints (auth, main, POS, productos, compras, admin, informes)
│   ├── templates/       # interfaz Jinja2 (español, sin escape manual de datos)
│   └── static/          # CSS/JS propios (sin CDN)
├── migrations/
│   ├── 001_init.sql     # esquema inicial (no se edita)
│   └── 002_seguridad_login.sql   # login_attempts persistente (ARQ-08)
├── tests/               # 45 pruebas + arnés DOM en tests/js/
├── tools/
│   ├── backup.py        # copia de seguridad .zip
│   ├── check_repo.py    # guardia anti-secretos antes de commitear
│   └── panel_licencias.py  # panel de la propietaria (fuera de la instalación)
├── docs/                # documentación técnica y de seguridad
├── .env.example · .gitignore · requirements.txt · requirements-dev.txt
└── run.py · wsgi.py · seed_demo.py
```

## Seguridad

Resumen de lo que el sistema hace y de lo que **no** promete:

- ✅ Datos del comercio insertados en el DOM **sólo** como texto (sin XSS).
- ✅ CSRF en todo cambio de estado; logout por POST.
- ✅ Consultas parametrizadas (sin inyección SQL).
- ✅ Contraseñas con hash `scrypt/pbkdf2` y sal; límite de intentos persistente.
- ✅ Dinero calculado con `Decimal` y redondeo comercial.
- ✅ Cabeceras de seguridad, sesión con vencimiento y errores 500 sin traceback.
- ⚠️ El comprobante interno **no** es una factura electrónica ante ARCA.
- ⚠️ SQLite es ideal para uso local con pocos puestos: no es un servidor de
  alta concurrencia.

Detalle completo: **`docs/SEGURIDAD.md`** y **`docs/AUDITORIA_HALLAZGOS.md`**.

## Operación diaria y copias de seguridad

`docs/OPERACION_Y_BACKUP.md` explica cómo abrir y cerrar el día, dónde viven
los datos, cómo hacer una copia y —lo más importante— **cómo restaurarla y
verificarla**.

## Documentación

| Documento | Contenido |
|---|---|
| `docs/ARQUITECTURA.md` | Capas, flujo de una venta, decisiones y límites |
| `docs/INSTALACION_LOCAL.md` | Instalación en Windows/Linux/macOS y primer arranque |
| `docs/OPERACION_Y_BACKUP.md` | Ubicación de datos, backup, restauración, cierre seguro |
| `docs/SEGURIDAD.md` | Secretos, usuarios, permisos, límites y respuesta a incidentes |
| `docs/AUDITORIA_HALLAZGOS.md` | Matriz ARQ-01…ARQ-17: evidencia, corrección y prueba |
| `docs/INFORME_PRUEBAS.md` | 45 pruebas reproducidas, con entorno y evidencia |
| `docs/INFORME_SEGURIDAD.md` | Informe de seguridad antes/después |
| `docs/MANUAL_USO.md` | Manual del usuario (borrador técnico de uso) |
| `docs/MANUAL_ADMINISTRACION.md` | Configuración, impuestos, usuarios, licencia |
| `docs/DESPLIEGUE.md` | Opciones de hosting y sus límites |
| `docs/LICENCIAS.md` | Sistema de licencias y panel central |
| `docs/FUNCIONALIDADES.md` | Terminado / pendiente |
| `docs/COSTOS.md` | Costos reales de operación |

## Publicar en GitHub

```bash
cd ferregest
python3 tools/check_repo.py      # debe responder CONTINUE
git init && git add . && git status --short
git commit -m "FerreGest AR — versión auditada"
git remote add origin https://github.com/TU-USUARIO/ferregest-ar.git
git push -u origin main
```

Antes del `push` confirme que **no** aparecen `ferregest.db`, `.secret`,
`.license_key`, `.env`, respaldos ni `tools/licencias_emitidas.jsonl`.
Todos están excluidos por `.gitignore`, pero la revisión final es manual.

## Licencia del código

Código original © 2026 — todos los derechos reservados (modelo comercial de
licencias por instalación controlado por la propietaria; ver
`docs/LICENCIAS.md`).
