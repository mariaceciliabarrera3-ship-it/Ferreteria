# Despliegue y operación — FerreGest AR

## Arquitectura económica

Monolito Python (Flask) + SQLite + Jinja2 + JS nativo. **Costo obligatorio mensual: $0.**
No hay servicios externos, APIs de pago, bases de datos alojadas ni CDNs obligatorios.

---

## Opción A — Servidor propio / VPS (recomendada para producción real)

Con un VPS Ubuntu (los más económicos rondan USD 4-6/mes; **no es obligatorio**):

```bash
sudo apt update && sudo apt install -y python3-venv nginx
git clone https://github.com/TU-USUARIO/ferregest-ar.git /opt/ferregest
cd /opt/ferregest && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export FERREGEST_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
# primer arranque: crea admin (cambie la clave) y migraciones
.venv/bin/python -c "from app import create_app; create_app()"
.venv/bin/python seed_demo.py     # solo si quiere datos de ejemplo
```

systemd (`/etc/systemd/system/ferregest.service`):

```ini
[Unit]
Description=FerreGest AR
After=network.target
[Service]
WorkingDirectory=/opt/ferregest
Environment=FERREGEST_SECRET=***
Environment=SESSION_COOKIE_SECURE=1
ExecStart=/opt/ferregest/.venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 wsgi:app
Restart=always
[Install]
WantedBy=multi-user.target
```

Nginx + certbot (HTTPS gratis con Let's Encrypt) delante de `127.0.0.1:8000`.

## Opción B — Hosting Python gratuito (sin tarjeta de crédito)

1. **PythonAnywhere** (plan gratuito, no pide tarjeta):
   - Suba el repositorio, cree una *Web app* Flask, apunte `wsgi.py`.
   - Límite: el plan gratuito solo atiende peticiones de forma intermitente
     (se "congela" entre peticiones) y sin dominio propio; la base de datos
     debe estar en el disco del plan (SQLite funciona).
   - Consecuencia: **puede haber latencia inicial** de varios segundos por
     petición. Para uso diario de una ferretería real se recomienda Option A.
2. **Otros proveedores con plan gratis** (Render, Railway, Fly, etc.):
   - Verificado en la documentación pública de los repos de partida:
     varios exigen **tarjeta o plan de pago para disco persistente**.
     Si el plan gratis no tiene disco, **SQLite no sobrevive a los
     redespliegues**: en ese caso use la exportación automática o cambie a
     PostgreSQL gratuito (ver «Migración a PostgreSQL»).
   - Si el servicio se duerme por inactividad, la primera petición tarda
     30-60 s. **No se declara despliegue exitoso sin URL operativa.**

> En esta entrega, la **URL de demostración activa** es la vista "Live Preview"
> provista por el entorno de evaluación, sirviendo este mismo código con la base
> demo sembrada.

## Opción C — Túnel temporal (demostraciones)

```bash
python3 run.py
cloudflared tunnel --url http://localhost:8000
```

Devuelve una URL `https://…trycloudflare.com` pública mientras su computadora
esté encendida. Gratis, sin registro, **no apto para producción** (se cae al
apagar la máquina).

---

## Migración de proveedor (portabilidad)

1. Copiar el repositorio tal cual al nuevo host.
2. Copiar `ferregest.db` (o restaurar el backup .zip).
3. `pip install -r requirements.txt && gunicorn wsgi:app`.
Las migraciones (`migrations/*.sql`) se aplican solas al arrancar.
**No hay que reconstruir nada**: la app es un WSGI estándar.

### Migración a PostgreSQL (opcional, futuro)

- Esquema SQL en `migrations/001_init.sql` (tipos estándar: TEXT/REAL/INTEGER).
- Reemplazar `app/db.py` por un adaptador con `psycopg` y traducir
  `?`→`%s`. Toda la lógica de negocio y plantillas quedan intactas.
- PostgreSQL gratuito sin tarjeta: Neon o Supabase (verificar límites vigentes).

---

## Copia de seguridad y restauración

```bash
python3 tools/backup.py                 # genera backup_YYYYmmdd_HHMMSS.zip
# restaurar:
# 1) detener app  2) reemplazar ferregest.db  3) iniciar
```

- El ZIP incluye la base consistente + `datos.json` legible.
- Desde la interfaz: **Licencias → Exportar datos del comercio (JSON)** —
  funciona **también con licencia suspendida**.
- Frecuencia recomendada: diaria (cron `0 2 * * * python3 /opt/ferregest/tools/backup.py`).
- Rotación: conserve los últimos 30 backups fuera del servidor.

## Desconexión y reactivación de una instalación

1. **Desconectar**: la propietaria emite una licencia vencida o suspendida
   (panel central). La instalación sigue accesible en modo lectura y permite
   exportar todo.
2. **Reactivar**: el cliente recibe una licencia nueva firmada y la pega en
   **Licencias → Importar**. Se recuperan todas las operaciones comerciales
   sin pérdida de datos (prueba 9 del informe).
