# Informe de pruebas — FerreGest AR

**Fecha de ejecución:** 2026-11-06 · **Entorno:** Python 3.13.16, Flask 3.1.3, SQLite
**Comando:** `python3 -m pytest tests/test_pruebas.py -v`
**Resultado: 12/12 APROBADAS** (salida completa en `informe_pruebas_raw.txt`).

Todas las pruebas se ejecutaron contra la aplicación real (test client de Flask
sobre la misma base y código de producción). **Ninguna prueba fue declarada
aprobada sin ejecutarse.**

| # | Prueba | Qué verifica | Resultado |
|---|---|---|---|
| 1 | Alta de producto | Cable por metro: costo $1.000, venta $1.500, stock 100; conversión 1 rollo = 100 m; movimiento `inventario_inicial` auditable | ✅ PASS |
| 2 | Venta fraccionada | 2,5 m → **total $3.750**, **stock 97,5**, movimiento de venta con Δ −2,5, renglón con cantidad decimal, cotización centralizada idéntica; rechazo de 1 rollo (100 m) con stock 97,5 (409); regla de stock negativo: sin permiso → 409; con autorización expresa del admin → −5 autorizado | ✅ PASS |
| 3 | Compra | Compra de 50 m a $1.100 → total $55.000; recepción ingresa al stock (+50), `cost_price` = 1.100 (reposición), `avg_cost` ponderado, movimiento `compra`; segunda compra con recepción parcial → estado `parcial` | ✅ PASS |
| 4 | Transferencia | Venta de $25.000 por transferencia: registrada con banco, **referencia `TR-99887766`**, cliente asociado, estado **`informada`** (nunca `verificada` automáticamente), venta en `pendiente_transferencia`; verificación manual admin → `verificada` + venta `pagada` | ✅ PASS |
| 5 | Impuestos | Creado `IVA Prueba 10%` (agregado, global, activo) → venta con impuesto: total $2.200 (imp. $200, desglose guardado); **desactivado** → venta nueva sin impuesto ($2.000); **histórica conserva $2.200 y su desglose**; historial de cambios en `tax_audit` | ✅ PASS |
| 6 | Caja | Apertura $10.000 + ingreso $5.000 + egreso $2.000 → cierre con contado $13.000: **esperado $13.000, diferencia $0**; segunda sesión con diferencia de $950 detectada en el arqueo | ✅ PASS |
| 7 | Devolución | Venta de 4 m (stock −4); devolución total → **stock repuesto**, movimiento `devolucion` +4, `sale_returns` por $6.000 con **egreso de caja** vinculado | ✅ PASS |
| 8 | Usuarios | Creado `vendetest` (rol vendedor): `/usuarios`, `/configuracion`, `/auditoria`, `/reportes?tab=ganancias` → **403**; `/pos` → 200 y venta exitosa (201); anular venta → **403** | ✅ PASS |
| 9 | Licencia | **activa** → opera; **por vencer** (5 días) → aviso y opera; **vencida en gracia** → aviso y opera; **suspendida** (30 días vencida) → venta 403 y `/pos` 403, pero `/ventas` y `/productos` 200, exportación 200 y **conteos de ventas/productos intactos**; **reactivada** → opera de nuevo y el conteo continúa sin pérdida | ✅ PASS |
| 10 | Persistencia | Nueva instancia de la aplicación + conexión independiente al archivo: ventas, productos, movimientos, clientes y proveedores **idénticos tras el "reinicio"** | ✅ PASS |
| 11 | Seguridad | Sin sesión: `/` y `/productos` → 302 a login, `/api/buscar` → **401**; POST sin CSRF → **400**; SQLi `'; DROP TABLE products;--` en 3 buscadores → 200 y **tabla intacta**; contraseña admin con hash `scrypt/pbkdf2` (no texto plano); cookie HttpOnly; cantidad negativa → 400; login con clave mala → **401** | ✅ PASS |
| 12 | Integridad económica | Toda venta activa: **total = suma de pagos** y **total = subtotal − descuentos + impuestos**; **stock de cada producto = Σ movimientos**; caja: ingresos de venta coherentes y saldo esperado calcule igual por dos vías; libro de clientes cuadra (debe − haber); anuladas excluidas | ✅ PASS |

## Pruebas complementarias (además de las 12 del pliego)

- Búsqueda global, cotización en vivo, importación CSV, exportaciones CSV/Excel,
  recepción parcial, cobros con transferencia pendiente, gastos con caja,
  auditoría con diff — ejercitadas también en la prueba de humo manual
  contra el servidor en ejecución (login + 16 rutas 200 + venta V-000030 real).

## Reproducción

```bash
cd ferregest
python3 -m pytest tests/test_pruebas.py -v
```

La suite crea su propia base aislada (`tests/tmp_ferregest_test.db`) y la
elimina al inicio de cada ejecución: es independiente de la base demo.

---

# Segunda ejecución — auditoría de arquitectura (7 de noviembre de 2026)

**Entorno:** Python 3.13.16 · Flask 3.1.3 · SQLite 3.46.1 · pytest 9.0.3 · Node 20
**Comando:** `python3 -m pytest tests/ -v`
**Resultado: 45/45 APROBADAS** (0 fallos, 0 omitidas).
**Evidencia cruda:** `docs/informe_pruebas_raw.txt` (salida completa, con fecha).

Las 12 pruebas del pliego original **siguen pasando** (sin adaptarlas al
criterio nuevo, salvo el logout que ahora es POST con CSRF por decisión de
seguridad: ARQ-10). A ellas se suman 33 pruebas nuevas de auditoría.

| Suite | Pruebas | Qué cubre |
|---|---:|---|
| `tests/test_pruebas.py` | 12 | Las 12 pruebas obligatorias del pliego |
| `tests/test_seguridad_arq.py` | 20 | ARQ-01 a ARQ-16: XSS (estático + arnés DOM), aislamiento de bases, GET sin escrituras, modo demo/producción, seed protegido, límite de login, logout POST, redirección abierta, cabeceras, error 500 sin traceback, CSRF y API sin sesión |
| `tests/test_dominio_arq.py` | 13 | ARQ-06/07/09/11/12: redondeo decimal, impuestos, ventas sin deriva de centavos, caja, migración atómica e idempotente, PRAGMAs, ventas simultáneas, dependencias y repositorio limpio |

## Prueba destacada: XSS con DOM real

`node tests/js/xss_harness.js` ejecuta `app/static/app.js` y
`app/static/pos.js` dentro de un DOM mínimo construido para la prueba, con un
producto y un cliente cuyo nombre es `<img src=x onerror=alert(1)>`:

```text
ok  - el buscador global muestra el payload como texto
ok  - el buscador global no crea <img>
ok  - el buscador global no crea <script>
ok  - la descripción viaja en un <strong> con textContent
ok  - el nombre del cliente viaja como texto
ok  - el POS muestra el payload como texto
ok  - el POS no crea <img>
ok  - el POS no crea <script>
ok  - se renderizaron los renglones del POS
ok  - el código hostil no generó atributos HTML
ok  - el carrito muestra la descripción como texto
ok  - el carrito no crea <img>
ok  - la primera celda del renglón es texto plano
ok  - el valor del medio de pago se conserva como valor, no como HTML
ok  - los medios de pago no crean <script>
ok  - escapeHtml escapa & < > " '
RESULTADO: CONTINUE — ningún dato de la base se interpreta como HTML.
```

**Control negativo (el arnés sirve de verdad):** al reintroducir a propósito
un `innerHTML = …` en `pos.js`, el arnés respondió
`RESULTADO: FIX — 3 comprobación(es) fallaron.` Se revirtió el cambio y volvió
a `CONTINUE`.

## Cómo reproducir

```bash
cd ferregest
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v
node tests/js/xss_harness.js          # opcional: requiere Node 18+
python3 tools/check_repo.py           # debe responder CONTINUE
```
