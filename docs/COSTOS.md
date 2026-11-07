# Costos reales de operación — FerreGest AR

## Stack y licencias (todo gratuito / código abierto)

| Componente | Licencia | Costo |
|---|---|---|
| Python 3 | PSF | $0 |
| Flask | BSD-3 | $0 |
| Gunicorn | MIT | $0 |
| SQLite | Domini público | $0 |
| openpyxl (Excel) | MIT | $0 |
| Jinja2 / Werkzeug | BSD-3 | $0 |
| pytest (desarrollo) | MIT | $0 |
| JS/CSS propio | — (sin CDN) | $0 |

**No hay:** APIs pagas, suscripciones, servicios de IA, bancos, proveedores de
SMS/email, dominios obligatorios ni pruebas gratuitas que facturen después.

## Costo mensual total de software: **$0**

Único costo opcional si se quiere dominio propio: ~USD 10-15/año de
registro de dominio (no lo exige el sistema).

## Alojamiento: opciones y límites (honestos)

| Opción | Costo | Límite documentado |
|---|---|---|
| Computadora local + túnel (cloudflared) | $0 | Solo mientras la máquina esté encendida; no apto 24/7 |
| PythonAnywhere gratis | $0 | Sin tarjeta. Consultas intermitentes (congelamiento), sin dominio propio, latencia inicial. Disco limitado (SQLite entra) |
| Render/Railway/Fly gratis | $0* | *El plan gratis típicamente **no conserva disco persistente** (Render lo indica: el bloque `disk` requiere plan de pago) y/o pide tarjeta. Sin disco, SQLite no sobrevive a redespliegues: riesgo de **pérdida de datos**. Documentado, no recomendado para producción |
| VPS económico (opcional) | USD ~4-6/mes | Recomendado para uso real 24/7 con HTTPS (ver DESPLIEGUE.md) |
| Servidor propio (opcional) | electricidad | Perfectamente viable: el sistema es muy liviano (2 workers gunicorn bastan) |

## Límites de la plataforma de demostración

La URL pública de esta entrega corre en el entorno de evaluación (preview en
vivo). Es apta para probar el sistema; para operación comercial continua se
recomienda la Opción A/B de `DESPLIEGUE.md`. **No se afirma un despliegue
permanente gratuito 24/7 sin sus límites documentados.**

## Conclusión

- Desarrollo, ejecución, pruebas y demo: **$0 obligatorios**.
- Producción mínima real y estable: desde **$0** (PythonAnywhere, con
  limitaciones de rendimiento) hasta ~USD 5/mes de VPS opcional.
