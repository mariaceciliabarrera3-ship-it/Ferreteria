# Matriz de hallazgos de arquitectura — FerreGest AR

**Fecha:** 7 de noviembre de 2026
**Alcance:** auditoría ARQ-01 a ARQ-12 del plan original + ARQ-13 a ARQ-16
encontrados durante la verificación línea por línea de este trabajo.
**Estado final:** 0 hallazgos críticos abiertos · 0 altos abiertos ·
2 medios con mitigación documentada.

Cada fila indica **dónde estaba el problema**, **qué se cambió** y **qué prueba
lo demuestra**. Todas las pruebas son reproducibles con:

```bash
python3 -m pytest tests/ -v          # 45 pruebas
python3 tools/check_repo.py          # control de secretos antes del commit
node tests/js/xss_harness.js         # arnés DOM de XSS (ARQ-01)
```

---

## 1. Resumen por severidad

| ID | Hallazgo | Severidad | Estado |
|---|---|---|---|
| ARQ-01 | XSS almacenado en buscador global, POS y compras (`innerHTML`) | Crítica | ✅ Cerrado |
| ARQ-02 | `create_app()` escribía `os.environ['FERREGEST_DB']` (global del proceso) | Alta | ✅ Cerrado |
| ARQ-03 | `load_state()` escribía en SQLite al renderizar cualquier página | Alta | ✅ Cerrado |
| ARQ-04 | Sin licencia, `ops_allowed=True`: no existía modo producción exigible | Alta | ✅ Cerrado |
| ARQ-05 | `seed_demo.py` con contraseñas fijas y capaz de pisar una instalación real | Alta | ✅ Cerrado |
| ARQ-06 | `requirements.txt` sin pytest (la doc mandaba instalarlo) | Media | ✅ Cerrado |
| ARQ-07 | ZIP con `.secret`, `ferregest.db` y `tests/tmp_ferregest_test.db` | Crítica | ✅ Cerrado |
| ARQ-08 | Límite de intentos en memoria: se pierde al reiniciar y no se comparte entre workers | Media | ✅ Cerrado (persistente) |
| ARQ-09 | Dinero en `float` con `round()` bancario | Alta | ✅ Cerrado (Decimal, HALF_UP) |
| ARQ-10 | Logout por GET (cambia estado de sesión) | Baja/Media | ✅ Cerrado (POST + CSRF) |
| ARQ-11 | Migraciones con `executescript()` sin transacción ni rollback | Media | ✅ Cerrado |
| ARQ-12 | SQLite sin `busy_timeout` ni prueba de concurrencia | Media | ✅ Cerrado |
| ARQ-13 | **Nuevo:** redirección abierta en `?next=` (aceptaba `//host`) | Alta | ✅ Cerrado |
| ARQ-14 | **Nuevo:** sin cabeceras de seguridad (CSP, `X-Frame-Options`, nosniff) | Media | ✅ Cerrado |
| ARQ-15 | **Nuevo:** sesión `permanent` sin vencimiento declarado | Baja | ✅ Cerrado (8 h) |
| ARQ-16 | **Nuevo:** error 500 podía filtrar el traceback al navegador | Media | ✅ Cerrado |
| ARQ-17 | **Nuevo:** `run.py` escuchaba en `0.0.0.0` por defecto | Media | ✅ Cerrado (`127.0.0.1`) |

---

## 2. Detalle por hallazgo

### ARQ-01 — XSS almacenado (CRÍTICO)

- **Evidencia original:** `app/static/app.js` (buscador global, armaba `html`
  con `p.description`, `c.name` y lo volcaba con `box.innerHTML = html`) y
  `app/static/pos.js` (`box.innerHTML` con `p.description`, `p.code`, `p.brand`;
  `body.innerHTML` del carrito con `l.description`; `renderPayAmounts` con
  valores escritos por el usuario). Tercer foco: `app/templates/compra_form.html`
  (`poRender`).
- **Riesgo real:** un producto llamado `<img src=x onerror=alert(1)>` se
  ejecutaba en el navegador de **toda** persona que abriera el POS. Con un
  payload peor, podía robar la sesión de la dueña.
- **Corrección:** se eliminó toda interpolación de datos en HTML.
  - `app/static/app.js`: helpers `escapeHtml()` y `el(tag, attrs, ...hijos)`;
    el buscador global construye `<a>` + `<strong>` con `textContent`.
  - `app/static/pos.js`: resultados, carrito y medios de pago se arman con
    `el()`/`textContent`; los `value` se asignan por propiedad.
  - `app/templates/compra_form.html`: `poRender()` con nodos DOM.
  - `app/templates/producto_form.html` y `producto_detalle.html`: mismos
    criterios (aunque su markup era estático).
- **Pruebas:**
  - `tests/test_seguridad_arq.py::test_arq01_js_no_usa_innerhtml` (estático,
    falla si alguien reintroduce `innerHTML`).
  - `tests/test_seguridad_arq.py::test_arq01_arnes_dom_en_node`: **arnés Node**
    (`tests/js/xss_harness.js`) que ejecuta `app.js` y `pos.js` contra un DOM
    mínimo con un payload real. Su DOM define `innerHTML` como setter que
    **lanza un error**: si el código volviera a usarlo, la prueba falla.
    Comprobación de control negativo realizada: al reintroducir un
    `innerHTML`, el arnés devolvió `FIX` con 3 comprobaciones fallidas.
  - `test_arq01_producto_y_cliente_hostil_se_renderiza_como_texto`: crea un
    producto y un cliente con el payload y verifica que el HTML los muestra
    escapados (`&lt;img …`) y que la API los devuelve crudos (el escape lo
    hace el cliente, como corresponde).
- **Limitación aceptada:** se mantienen scripts inline en las plantillas, por
  lo que la CSP incluye `'unsafe-inline'` en `script-src`. Pasar a nonces
  queda como mejora futura documentada.

### ARQ-02 — Aislamiento de la base por instancia (ALTA)

- **Evidencia original:** `app/__init__.py` hacía
  `os.environ["FERREGEST_DB"] = db_path`; `app/db.py::current_db_path()` leía
  esa variable global. Dos apps en el mismo proceso compartían la base.
- **Corrección:** la ruta vive en `app.config["FERREGEST_DB"]`
  (resuelta por `app/config.py::resolve_db_path`) y `current_db_path()` la lee
  desde `flask.current_app` cuando hay contexto de aplicación; fuera de la app
  (CLI/herramientas) sigue usando `FERREGEST_DB`. `create_app()` ya no toca el
  entorno.
- **Prueba:** `test_arq02_dos_instancias_con_dos_bases` — dos apps, dos bases,
  productos distintos, y `FERREGEST_DB` ausente del entorno después de crearlas.

### ARQ-03 — Leer no debe escribir (ALTA)

- **Evidencia original:** `license.load_state()` terminaba con
  `UPDATE license_info SET last_check = ?` y era invocada por el
  `context_processor`, es decir, **en cada renderizado de página**.
- **Corrección:** se separaron las responsabilidades:
  - `get_state()`: sólo lectura (la usan plantillas y `assert_ops_allowed`).
  - `record_check()`: la única escritura, llamada al arrancar la app y al
    importar una licencia.
  - `get_install_id(create=False)`: por defecto no inserta nada.
  - `load_state(record=False)` queda como alias de compatibilidad.
- **Prueba:** `test_arq03_renderizar_no_modifica_la_base` — 25 GETs sobre
  cinco rutas y `last_check` no cambia.

### ARQ-04 — Modo demo / producción (ALTA)

- **Evidencia original:** sin payload de licencia el estado dejaba
  `ops_allowed=True` con el comentario «en producción emisión de licencia es
  obligatoria», pero **ningún código lo exigía**.
- **Corrección:** `app/config.py::mode()` lee `FERREGEST_MODE`
  (`demo` por defecto, `production` explícito). En producción, una licencia
  ausente, inválida, vencida fuera de gracia o suspendida fija
  `ops_allowed=False` y muestra un aviso; lectura, informes, exportación y
  backups siguen disponibles. Con licencia válida verificada se rehabilita.
- **Pruebas:** `test_arq04_produccion_sin_licencia_bloquea_ventas` (403 sin
  licencia, 201 tras importar una licencia firmada válida) y
  `test_arq04_modo_demo_permite_operar`.

### ARQ-05 — Seed de demostración seguro (ALTA)

- **Evidencia original:** `seed_demo.py` fijaba `admin123`, `vendedor123` y
  `deposito123` y **actualizaba la contraseña del usuario admin** si lo
  encontraba, incluso en una instalación con datos reales.
- **Corrección:** cinco candados (documentados en el propio script):
  1. exige `FERREGEST_MODE=demo`;
  2. exige `--confirmar-demo` o `FERREGEST_SEED_DEMO=1`;
  3. se niega a correr si la base ya tiene ventas, compras, clientes, caja,
     movimientos o auditoría;
  4. sin contraseñas fijas: las toma de `FERREGEST_DEMO_*_PASSWORD` y, si no
     están, genera claves aleatorias que muestra y guarda en
     `var/claves_demo.txt` (0600);
  5. no cambia la clave de usuarios existentes salvo
     `--rotar-claves-demo`.
- **Prueba:** `test_arq05_seed_demo_exige_confirmacion` (subprocess: se niega
  sin confirmación, se niega en producción y no deja claves fijas en el
  código).

### ARQ-06 — Dependencias de desarrollo (MEDIA) ✅

- `requirements-dev.txt` con `-r requirements.txt` y `pytest>=8,<10`.
  Documentado en el README. `requirements.txt` no contamina la instalación del
  comercio con herramientas de desarrollo.
- **Prueba:** `test_arq06_dependencias_de_prueba_documentadas`.

### ARQ-07 — Secretos y bases fuera del repositorio (CRÍTICA) ✅

- Se eliminaron del árbol publicable `.secret`, `ferregest.db` y
  `tests/tmp_ferregest_test.db`. `.gitignore` ampliado (bases y sus `-wal`,
  `-shm`, `-journal`, `.env*`, `*.key`, `var/`, respaldos, exportaciones,
  `licencias_emitidas.jsonl`).
- `.env.example` documenta las variables **sin valores reales**.
- `tools/check_repo.py` bloquea el commit si vuelven a aparecer (y entiende
  `git check-ignore` para no dar falsos positivos).
- **Tratamiento del secreto expuesto:** el `.secret` que viajó en el ZIP se
  considera **comprometido**: no se reutiliza. La instalación local genera uno
  nuevo en el primer arranque (o define `FERREGEST_SECRET`).
- **Pruebas:** `test_arq07_el_repositorio_no_contiene_secretos_ni_bases`,
  `test_arq07_gitignore_cubre_bases_y_secretos`,
  `test_arq07_plantilla_de_variables_sin_valores_reales`.

### ARQ-08 — Límite de intentos persistente (MEDIA) ✅

- **Evidencia original:** `_FAILED = {}` en `app/bp_auth.py`: por proceso, se
  perdía al reiniciar y cada worker contaba por separado.
- **Corrección:** tabla `login_attempts` (migración `002_seguridad_login.sql`)
  + `app/security.py::register_login_failure`, `login_failures`,
  `login_locked`, `clear_login_failures`. Ventana configurable
  (`FERREGEST_LOGIN_WINDOW_MINUTES`, 60), umbral
  (`FERREGEST_LOGIN_MAX_ATTEMPTS`, 8) y bloqueo temporal
  (`FERREGEST_LOGIN_LOCKOUT_MINUTES`, 15). Si la tabla no existe cae a memoria
  y lo documenta.
- **Prueba:** `test_arq08_bloqueo_de_login_persistente` — 8 intentos fallidos
  → 429; **otra instancia** de la app sobre la misma base sigue viendo el
  bloqueo (demuestra que ya no es estado de memoria).

### ARQ-09 — Dinero en Decimal (ALTA) ✅

- **Evidencia original:** acumuladores en `float` y `round()` (redondeo
  bancario: `round(2.675, 2) == 2.67`) en `app/db.py::round2`,
  `app/fiscal.py` y `app/services.py`.
- **Corrección:** módulo nuevo `app/money.py` (`D`, `q2`, `q4`, `f2`, `f4`,
  `sum_q2`, `money_str`) con `ROUND_HALF_UP`; los servicios acumulan en
  `Decimal` y sólo convierten a `float` al escribir en la columna `REAL`.
  `round2()` pasa por `money.q2()`.
- **Pruebas:** `test_arq09_redondeo_comercial`,
  `test_arq09_impuestos_agregado_e_incluido`,
  `test_arq09_venta_sin_deriva_de_centavos` (100 ventas de $0,01 suman
  exactamente $1,00), `test_arq09_renglon_con_fracciones_y_descuento`,
  `test_arq09_caja_suma_sin_error_acumulado` (100 ingresos de $0,10 = $10,00).
- **Limitación aceptada:** la columna sigue siendo `REAL`. El valor guardado ya
  viene cuantizado, por lo que no hay deriva acumulada; migrar a enteros en
  centavos sería una migración de esquema mayor y se deja planificada.

### ARQ-10 — Logout por POST (BAJA/MEDIA) ✅

- `app/bp_auth.py`: la ruta acepta **sólo POST** (con CSRF); GET da 405.
- `app/templates/base.html`: formulario con token y botón con el mismo
  aspecto (CSS agregado en `app/static/app.css`).
- **Prueba:** `test_arq10_logout_exige_post_y_csrf`.

### ARQ-11 — Migraciones transaccionales (MEDIA) ✅

- **Corrección:** `app/db.py::migrate()` aplica **una transacción por archivo**
  (`BEGIN IMMEDIATE` → sentencias → `INSERT schema_migrations` → `COMMIT`),
  con `ROLLBACK` y error contextual si algo falla. Las sentencias se separan
  con `sqlite3.complete_statement` (entiende bloques `CREATE TRIGGER … END;`).
  Antes de empezar copia la base a `var/migration-backups/`. El registro en
  `schema_migrations` ocurre **dentro** de la misma transacción, así que una
  migración interrumpida no queda marcada como aplicada.
- **Pruebas:** `test_arq11_migracion_fallida_no_deja_esquema_a_medias`
  (inyecta una migración con SQL inválido: no queda la tabla ni el registro),
  `test_arq11_migraciones_registradas_e_idempotentes`.

### ARQ-12 — SQLite y concurrencia (MEDIA) ✅

- **Corrección:** `PRAGMA busy_timeout` (8 s, configurable),
  `journal_mode=WAL`, `synchronous=NORMAL`; las transacciones de negocio usan
  `BEGIN IMMEDIATE` (`app/db.py::begin_immediate`) para evitar
  `SQLITE_BUSY` por upgrade de lock. Límite realista documentado: 1 proceso de
  escritura efectivo; más workers no mejora SQLite.
- **Pruebas:** `test_arq12_pragma_de_espera_configurado` y
  `test_arq12_ventas_simultaneas_no_pierden_stock` (8 hilos × 5 ventas sobre el
  mismo producto: stock, cantidad de ventas y Σ movimientos cuadran).

### ARQ-13 — Redirección abierta en `?next=` (ALTA, hallazgo nuevo) ✅

- **Evidencia:** `bp_auth.login()` validaba `dest.startswith("/")`. Eso acepta
  `//evil.com` y `/\evil.com`, que el navegador interpreta como **otro host**:
  phishing con la URL del comercio como señuelo.
- **Corrección:** `safe_next()` en `app/bp_auth.py` rechaza `//`, `/\` y
  cualquier destino con esquema o host (`urlparse`).
- **Prueba:** `test_arq13_next_no_redirige_fuera_del_sitio` (4 variantes
  hostiles) y `test_arq13_next_interno_si_funciona`.

### ARQ-14 — Cabeceras de seguridad (MEDIA, hallazgo nuevo) ✅

- `after_request` agrega `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: same-origin`,
  `Permissions-Policy` y una CSP (`default-src 'self'`, `object-src 'none'`,
  `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'self'`).
  Las páginas autenticadas se sirven con `Cache-Control: no-store`.
- **Prueba:** `test_arq14_cabeceras_de_seguridad`.

### ARQ-15 — Vencimiento de sesión (BAJA, hallazgo nuevo) ✅

- `PERMANENT_SESSION_LIFETIME` = 8 h (`FERREGEST_SESSION_HOURS` configurable)
  en lugar de una sesión permanente indefinida.
- Documentado en `.env.example`.

### ARQ-16 — Errores 500 sin traceback (MEDIA, hallazgo nuevo) ✅

- Handler 500 que registra el detalle en el log del servidor y devuelve al
  navegador un mensaje con **id de incidente**. La página de error
  (`error.html`) se ve también sin sesión iniciada.
- **Prueba:** `test_arq16_error_500_no_filtra_el_traceback`.

### ARQ-17 — Superficie de red por defecto (MEDIA, hallazgo nuevo) ✅

- `run.py` escuchaba en `0.0.0.0` (expuesto en toda la LAN). Ahora el defecto
  es `127.0.0.1` y se puede ampliar con `FERREGEST_HOST`.

---

## 3. Hallazgos que NO se cerraron (aceptados con mitigación)

| ID | Limitación | Mitigación | Responsable |
|---|---|---|---|
| LIM-01 | CSP con `'unsafe-inline'` (hay scripts inline en plantillas) | Los datos del usuario nunca se interpolan en HTML (ARQ-01); migrar a nonces queda planificado | Desarrollo |
| LIM-02 | Columnas monetarias `REAL` (no enteros en centavos) | Todo el cálculo es `Decimal` y se cuantiza antes de persistir; pruebas de acumulación | Desarrollo |
| LIM-03 | SQLite soporta un escritor a la vez | `busy_timeout` 8 s, WAL, `BEGIN IMMEDIATE`, límite de concurrencia documentado | Operación |
| LIM-04 | Las contraseñas no tienen política de complejidad completa | Mínimo 8 caracteres + lista negra de claves obvias; se recomienda clave única por usuario | Administración |

## 4. Cómo reproducir la auditoría completa

```bash
cd ferregest
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v                # 45 pruebas
node tests/js/xss_harness.js               # arnés DOM (opcional, requiere Node)
python3 tools/check_repo.py                # debe decir CONTINUE
python3 -m compileall -q app tools run.py wsgi.py seed_demo.py
```
