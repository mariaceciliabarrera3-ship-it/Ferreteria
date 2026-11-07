# Informe de seguridad — FerreGest AR

## 1. Autenticación y contraseñas

- Hash con **Werkzeug `generate_password_hash`** (scrypt/pbkdf2, con sal):
  verificado en la prueba 11 (ningún hash contiene la clave en texto plano).
- Sesiones firmadas por Flask (`SECRET_KEY` generada automáticamente en
  `.secret` con permisos 0600 o en `FERREGEST_SECRET`).
- Cookies: `HttpOnly`, `SameSite=Lax`, `Secure` configurable
  (`SESSION_COOKIE_SECURE=1` tras HTTPS).
- Bloqueo tras 8 intentos fallidos de login (429) + auditoría de cada intento.
- Logout limpia la sesión completa.

## 2. Protección CSRF

- Token por sesión (16 bytes aleatorios) inyectado en todas las páginas
  (`meta` + campo `_csrf`).
- **Todo POST/PUT/PATCH/DELETE** se valida en `before_request`
  (`secrets.compare_digest`, sin comparaciones con timing vulnerable).
  Prueba 11: POST sin token → 400.

## 3. Inyección SQL

- Todas las consultas usan **parámetros posicionales** (`?`) de `sqlite3`:
  nunca se concatenan valores del usuario.
- Prueba 11: `'; DROP TABLE products;--` en tres buscadores distintos →
  respuesta 200 y tabla intacta.

## 4. Autorización

- Decoradores `login_required` y `permission_required(perm)` + control por
  rol/permiso en cada servicio crítico (servidor, no solo UI).
- Separación verificada (prueba 8): vendedor sin acceso a usuarios,
  configuración, auditoría ni informes de ganancias, y sin capacidad de
  anular ventas.
- Verificación de transferencias, cierre de caja, modificación de precios,
  licencias y configuración fiscal requieren permisos explícitos.
- **Validación en servidor** de todas las entradas (rangos, tipos, sumas de
  pagos == total, unidades existentes, stock, límites de crédito).

## 5. Integridad transaccional

- Escrituras de negocio en **transacciones explícitas** (`BEGIN/COMMIT/ROLLBACK`):
  una venta fallida no deja movimientos parciales (prueba 12: stock =
  Σ movimientos en el 100 % de los productos).

## 6. Autorización fiscal honesta

- **No se simula** facturación electrónica, CAI, sellos ni autorización ARCA.
- El comprobante declara explícitamente que es interno de gestión.
- Impuestos desactivados por defecto; configuración a cargo del administrador
  con aviso de validación profesional y historial auditable.

## 7. Licenciamiento sin espionaje

- Verificación local con HMAC-SHA256; **cero llamadas de red** desde la app
  a servidores de la propietaria.
- La suspensión no destruye datos ni incluye mecanismos de remoción remota.

## 8. Datos y backups

- Un archivo SQLite por instalación (aislamiento total entre comercios).
- Exportación JSON + backup `.zip` con `sqlite3.backup` consistente.
- `.gitignore` impide subir la base, secretos o claves de licencia.

## 9. Dependencias

- Solo `flask`, `gunicorn`, `openpyxl` (+ `pytest` para desarrollo): proyectos
  maduros, licencias libres, sin binarios de terceros cerrados.
- Sin CDN ni JS externos: la UI funciona sin dependencias de red de terceros
  (reduce superficie de ataque y funciona en el iframe de evaluación).

## 10. Limitaciones conocidas (honestidad)

- Sin HTTPS propio en la demo del entorno (el proxy de evaluación lo termina
  en su borde); en producción se documenta nginx + Let's Encrypt.
- Sin 2FA (posible mejora futura).
- Rate limiting de login es por proceso (no sirve si hay múltimos workers;
  mitigable con nginx `limit_req` — documentado en DESPLIEGUE.md).
- El secreto de firma de licencias vive fuera del repo (entorno de la
  propietaria), como corresponde.

---

# Segunda revisión de seguridad (7 de noviembre de 2026)

Alcance: verificación línea por línea de los 12 hallazgos ARQ-01…ARQ-12 más
cuatro hallazgos nuevos encontrados en esta revisión (ARQ-13 a ARQ-16) y uno
adicional de superficie de red (ARQ-17). Todos están **cerrados y probados**;
el detalle completo está en `docs/AUDITORIA_HALLAZGOS.md`.

## 11. Correcciones aplicadas en esta revisión

| ID | Antes | Ahora |
|---|---|---|
| ARQ-01 | Datos de productos/clientes en `innerHTML` (XSS almacenado) | Nodos DOM con `textContent` + `escapeHtml()`; arnés Node de 16 comprobaciones |
| ARQ-02 | `create_app()` escribía `os.environ['FERREGEST_DB']` | Ruta en `app.config['FERREGEST_DB']`; dos instancias con dos bases aisladas |
| ARQ-03 | `load_state()` escribía `last_check` al renderizar cualquier página | `get_state()` (sólo lectura) y `record_check()` explícito |
| ARQ-04 | Sin licencia se operaba igual; no existía modo producción | `FERREGEST_MODE=demo|production`; producción bloquea operaciones sin licencia válida |
| ARQ-05 | `seed_demo.py` con claves fijas y capaz de pisar datos reales | Exige modo demo + confirmación, rechaza bases con datos y genera claves aleatorias |
| ARQ-07 | ZIP con `.secret`, `ferregest.db` y base de pruebas | Fuera del repositorio; `.gitignore` ampliado; `tools/check_repo.py` como guardia |
| ARQ-08 | Límite de intentos en memoria (por proceso) | Tabla `login_attempts` persistente con ventana y bloqueo temporales |
| ARQ-09 | Dinero en `float` y `round()` bancario | `app/money.py` con `Decimal` y `ROUND_HALF_UP`; acumulación sin deriva |
| ARQ-10 | Logout por GET | POST + CSRF (GET → 405) |
| ARQ-11 | `executescript()` sin transacción | Una transacción por migración, `ROLLBACK` ante fallo y copia previa |
| ARQ-12 | Sin `busy_timeout` ni prueba de concurrencia | `busy_timeout` 8 s, WAL, `BEGIN IMMEDIATE` y prueba con 8 hilos |
| ARQ-13 | `?next=` aceptaba `//host` (redirección abierta) | `safe_next()`: sólo rutas internas |
| ARQ-14 | Sin cabeceras de seguridad | CSP, nosniff, `X-Frame-Options`, `Referrer-Policy`, `no-store` |
| ARQ-15 | Sesión `permanent` sin vencimiento | `PERMANENT_SESSION_LIFETIME` de 8 h configurable |
| ARQ-16 | El error 500 podía mostrar el traceback | Handler propio con id de incidente; detalle sólo en el log |
| ARQ-17 | `run.py` escuchaba en `0.0.0.0` | `127.0.0.1` por defecto (`FERREGEST_HOST` para cambiarlo) |

## 12. Corrección de una afirmación anterior

En la primera versión de este informe se escribió: *“Rate limiting de login es
por proceso (no sirve si hay múltiples workers)”*. Esa limitación **ya no
aplica**: el contador vive en SQLite. Lo que sigue vigente es que el bloqueo
no defiende contra ataques distribuidos desde muchas IP; para eso sigue
recomendándose `limit_req` en el proxy (ver `docs/DESPLIEGUE.md`).

## 13. Verificación

- `python3 -m pytest tests/ -v` → **45 pruebas en verde**
  (12 del pliego + 33 de auditoría).
- `node tests/js/xss_harness.js` → `CONTINUE` (16 comprobaciones) y falla
  cuando se reintroduce el defecto (control negativo ejecutado).
- `python3 tools/check_repo.py` → `CONTINUE` (sin secretos, bases ni respaldos).
