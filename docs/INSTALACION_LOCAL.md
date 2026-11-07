# Instalación local — FerreGest AR

Instrucciones para instalar FerreGest en la computadora del comercio
(Windows, Linux o macOS). **No requiere cuenta paga, ni servicios externos,
ni conexión permanente a Internet.**

> ⚠️ **No ejecute `seed_demo.py` sobre la instalación real.** El seed es
> exclusivo de una base de demostración (ver ARQ-05).

---

## 1. Requisitos

| Requisito | Versión probada | Notas |
|---|---|---|
| Python | 3.13 (compatible desde 3.10) | Descargar de python.org |
| Disco | 200 MB libres | La base crece poco (kilobytes por miles de ventas) |
| Navegador | Chrome, Edge o Firefox actual | No se necesita Internet para usar la app |

Todo lo demás (Flask, SQLite, openpyxl) se instala con `pip`.

## 2. Instalación paso a paso

### Windows (PowerShell)

```powershell
cd C:\FerreGest
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Si PowerShell bloquea los scripts:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Linux / macOS

```bash
cd ~/FerreGest
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Elegir dónde viven los datos

Cree una carpeta **fuera del código** y con respaldo, por ejemplo:

- Windows: `C:\FerreGest\datos\ferregest.db`
- Linux/macOS: `~/FerreGest/datos/ferregest.db`

No la ponga en OneDrive, Dropbox, Google Drive ni en una unidad de red: SQLite
y la sincronización en la nube se llevan mal (ARQ-12).

## 4. Configurar el entorno

Copie `.env.example` como `.env` en la carpeta del proyecto y complete:

| Variable | Obligatoria | Recomendación en el comercio |
|---|---|---|
| `FERREGEST_MODE` | Sí | `production` cuando opere de verdad; `demo` mientras prueba |
| `FERREGEST_DB` | Sí | Ruta absoluta del punto 3 |
| `FERREGEST_SECRET` | Recomendada | Clave larga y aleatoria (si falta, se genera `.secret` con 0600) |
| `FERREGEST_ADMIN_PASSWORD` | Sí (primer arranque) | Clave única, propia; **nunca** `admin123` |
| `SESSION_COOKIE_SECURE` | Si usa HTTPS | `1` sólo detrás de HTTPS |
| `PORT` | No | `8000` por defecto |
| `FERREGEST_HOST` | No | `127.0.0.1` por defecto (no se expone en la red) |

Cargar las variables:

- Windows PowerShell: `setx FERREGEST_MODE production` (y repetir por variable;
  hay que abrir una terminal nueva).
- Linux/macOS: `export FERREGEST_MODE=production` (o usar un archivo `.env`
  cargado por el servicio).

## 5. Primer arranque

```bash
python3 run.py          # Linux/macOS
python run.py           # Windows
```

Abrir <http://127.0.0.1:8000> e ingresar:

- Usuario: `admin`
- Contraseña: la de `FERREGEST_ADMIN_PASSWORD`.
  - En modo **producción**, si no se definió, el sistema genera una aleatoria y
    la guarda en `var/clave_inicial_admin.txt` (permisos 0600).
  - En modo **demo**, si no se definió, se usa `admin123` **y se muestra un
    aviso**: cámbiela de inmediato.

Primeros pasos recomendados:

1. **Mi cuenta → Cambiar contraseña.**
2. Configuración → datos del negocio (nombre, dirección, CUIT, condición de IVA).
3. Configuración → impuestos (desactivados por defecto: actívelos según el
   criterio de su contador).
4. Usuarios → crear un usuario por empleado con el rol y los permisos reales.
5. Productos → cargar el inventario (o importar CSV/XLSX).
6. Caja → abrir sesión antes de empezar a vender.
7. Hacer **una venta de prueba ficticia** y anularla para verificar el circuito.

## 6. Verificación de la instalación

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v       # usa bases temporales: no toca sus datos
python3 tools/check_repo.py       # debe decir CONTINUE
```

Las pruebas crean su propia base temporal (`tests/tmp_*.db`) y nunca leen ni
modifican la base del comercio.

## 7. Actualizar a una versión nueva

1. Haga una copia de seguridad (`python3 tools/backup.py`).
2. Reemplace el código (git pull o descarga del ZIP).
3. `pip install -r requirements.txt`.
4. Inicie la aplicación: las migraciones pendientes se aplican solas, de forma
   transaccional, con copia previa en `var/migration-backups/`.
5. Verifique que puede ingresar y ver una venta conocida.

## 8. Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| «database is locked» | Otro proceso está escribiendo o la base está en carpeta sincronizada. Cierre la otra instancia; saque la base de OneDrive/Dropbox |
| No abre el navegador en otra computadora | Por defecto escucha sólo en `127.0.0.1`. Para usarla en la red local: `FERREGEST_HOST=0.0.0.0` (y cortafuegos/Seguridad evaluados) |
| «Token CSRF inválido» | La sesión venció (8 h) o se abrieron dos pestañas con sesiones distintas. Recargue la página y reintente |
| Aparece el aviso de licencia y no deja vender | Está en `FERREGEST_MODE=production` sin licencia válida. Importe la licencia en Administración → Licencia |
| Se olvidó la contraseña de admin | No hay recuperación por correo: un administrador con acceso a la base puede reemplazar el hash, o restaure una copia de seguridad |
