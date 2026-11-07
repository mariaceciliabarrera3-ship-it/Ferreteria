# Arquitectura — FerreGest AR

**Versión:** posterior a la auditoría ARQ-01…ARQ-17 (7 de noviembre de 2026)
**Estado:** arquitectura aprobada con las correcciones y limitaciones descritas
en `docs/AUDITORIA_HALLAZGOS.md`.

---

## 1. Vista general

```text
Navegador (red local o 127.0.0.1)
        │  HTTP  (cookie de sesión HttpOnly + SameSite=Lax)
        ▼
Flask app factory  create_app(db_path)
        │
        ├── before_request ──── CSRF en POST/PUT/PATCH/DELETE + token de sesión
        ├── after_request ───── cabeceras de seguridad (CSP, nosniff, …)
        ├── context_processor   usuario, permisos, estado de licencia (sólo lectura)
        ├── errorhandlers ───── 400/401/403/404/409/500 (sin filtrar tracebacks)
        │
        ├── Blueprints (capa de presentación)
        │     auth  · main  · pos  · products  · purchases  · admin  · reports
        │
        ├── Servicios de negocio (app/services.py) — TODO lo que escribe
        │     ventas y devoluciones · compras y recepciones
        │     stock y movimientos · caja · cuentas corrientes
        │     transferencias (verificación manual)
        │
        ├── Dominio de soporte
        │     fiscal.py    impuestos, márgenes, valorización
        │     money.py     aritmética decimal (ARQ-09)
        │     license.py   licencia firmada local (HMAC-SHA256)
        │     security.py  sesión, permisos, CSRF, auditoría, límite de login
        │
        └── Persistencia (app/db.py)
              SQLite (un archivo por comercio, WAL)
              migraciones SQL numeradas y transaccionales
```

## 2. Capas y responsabilidades

| Capa | Archivos | Regla |
|---|---|---|
| Presentación | `app/templates/*.html`, `app/static/*.js|css` | No decide permisos; no arma HTML con datos (usa `textContent`/`el()`) |
| Rutas | `app/bp_*.py` | Valida entrada y delega; nunca escribe directo en tablas de negocio |
| Servicios | `app/services.py` | Única vía de escritura; transacciones `BEGIN IMMEDIATE` |
| Dominio | `fiscal.py`, `money.py`, `license.py`, `security.py` | Cálculo y reglas, sin depender de la request |
| Datos | `app/db.py`, `migrations/*.sql` | Acceso parametrizado, migraciones versionadas |

## 3. Flujo de una venta (el camino crítico)

1. `POST /api/ventas` (JSON) → token CSRF por cabecera.
2. `bp_pos` valida sesión y delega a `services.create_sale`.
3. `create_sale`:
   - `assert_ops_allowed()` → estado de licencia **sin escribir** (ARQ-03/04).
   - `BEGIN IMMEDIATE` (ARQ-12).
   - Recalcula precios e impuestos **en el servidor** con `Decimal` (ARQ-09);
     nunca confía en los importes que mandó el navegador.
   - Verifica permisos de descuento y de stock negativo.
   - Descuenta stock generando movimientos auditables.
   - Registra pagos; las transferencias quedan `pendiente`/`informada`,
     **nunca** verificadas automáticamente.
   - Mueve caja y cuenta corriente si corresponde.
   - `COMMIT`; ante cualquier excepción, `ROLLBACK` (no quedan movimientos
     a medias).
4. Respuesta `201` con la venta; el navegador salta al comprobante interno.

## 4. Decisiones de diseño y por qué

| Decisión | Motivo |
|---|---|
| Flask + SQLite, un archivo por comercio | Presupuesto cero, instalación local, copias de seguridad triviales |
| `app.config['FERREGEST_DB']` en vez de `os.environ` | Dos instancias en un mismo proceso no se pisan (ARQ-02) |
| Migraciones numeradas inmutables + transacción por archivo | Una instalación ya aplicada no se rompe; una fallida se revierte (ARQ-11) |
| `Decimal` para dinero | `round()` bancario y `float` desplazaban centavos en una ferretería (ARQ-09) |
| Licencia verificada 100 % local (HMAC) | Sin llamadas externas: no sale información comercial del comercio |
| Modo explícito `demo`/`production` | Sin licencia, producción falla de forma segura en lugar de operar igual (ARQ-04) |
| Datos al DOM con `textContent` | Un nombre de producto no puede ejecutar código (ARQ-01) |
| `127.0.0.1` por defecto | La caja de una ferretería no debe publicarse en la red sin decidirlo (ARQ-17) |

## 5. Límites conocidos de la arquitectura

1. **SQLite escribe de a uno.** Con WAL y `busy_timeout`, varios lectores y un
   escritor funcionan bien; más procesos de escritura **no** mejoran el
   rendimiento. No alojar el archivo `.db` en carpetas sincronizadas
   (OneDrive/Dropbox) ni en unidades de red.
2. **Un comercio = una base.** No hay multi-tenencia: para dos comercios, dos
   carpetas y dos bases.
3. **El comprobante no es factura electrónica.** El sistema no emite
   comprobantes fiscales ante ARCA: es una herramienta de gestión interna.
4. **Scripts inline en las plantillas** obligan a `'unsafe-inline'` en la CSP.
   Los datos se insertan como texto, pero conviene migrar a nonces.
5. **Alta concurrencia o acceso remoto** requieren otra infraestructura
   (persistencia y presupuesto), lo cual queda fuera de este alcance.

## 6. Mapa de archivos

| Archivo | Rol |
|---|---|
| `app/__init__.py` | factoría, filtros, cabeceras, handlers de error, bootstrap |
| `app/config.py` | modo, ruta de base, umbrales de login, timeouts (ARQ-02/04) |
| `app/db.py` | conexión, PRAGMAs, transacciones, migraciones atómicas |
| `app/money.py` | `Decimal` y redondeo comercial (ARQ-09) |
| `app/security.py` | sesión, roles/permisos, CSRF, auditoría, límite de login |
| `app/license.py` | licencia local firmada; `get_state()` sin efectos (ARQ-03) |
| `app/services.py` | transacciones de negocio |
| `app/fiscal.py` | impuestos, márgenes, valorización |
| `app/bp_*.py` | rutas por módulo |
| `migrations/001_init.sql` | esquema inicial (no se edita) |
| `migrations/002_seguridad_login.sql` | `login_attempts` (ARQ-08) |
| `tests/` | 45 pruebas: pliego + auditoría + arnés DOM |
| `tools/check_repo.py` | control de secretos previo al commit |
| `tools/backup.py` | copia de seguridad en ZIP |
| `tools/panel_licencias.py` | panel de la propietaria (fuera de la instalación) |
