# Seguridad — FerreGest AR

**Estado:** informe posterior a la auditoría ARQ-01…ARQ-17 (7 de noviembre
de 2026). Detalle de cada hallazgo en `docs/AUDITORIA_HALLAZGOS.md`.

---

## 1. Secretos y credenciales

| Secreto | Dónde vive | Nunca |
|---|---|---|
| Clave de sesión | `FERREGEST_SECRET` o `.secret` (permisos 0600, generado una vez) | En el repositorio, en correos, en capturas |
| Clave de firma de licencias | `LICENSE_SIGNING_KEY`, **sólo** en el entorno de la propietaria | En la instalación del comercio ni en GitHub |
| Contraseñas de usuarios | Hash `scrypt/pbkdf2` con sal (Werkzeug) | En texto plano, en logs, en la base de auditoría |
| Base de datos | Archivo local del comercio | En carpetas compartidas o sincronizadas |

- **El `.secret` que viajó en el ZIP original se considera comprometido**: no
  se reutiliza. Cada instalación genera el suyo en el primer arranque.
- `.env.example` documenta variables **sin valores reales**; `.env` está
  excluido del repositorio.
- `tools/check_repo.py` impide commitear secretos, bases o respaldos:

```bash
python3 tools/check_repo.py            # árbol de trabajo
python3 tools/check_repo.py --staged   # lo que está por commitearse
```

### Si un secreto se expuso

1. **Rote** el secreto (generar uno nuevo; no alcanza con borrarlo del commit).
2. Revise la bitácora (**Auditoría**) buscando accesos que no reconozca.
3. Cambie las contraseñas de los usuarios afectados.
4. Borre el historial de Git sólo con un procedimiento controlado, y asuma que
   lo que se publicó ya fue copiado.

## 2. Autenticación y sesión

- Hash moderno con sal (Werkzeug); mínimo 8 caracteres y lista negra de claves
  obvias (`admin123`, `12345678`, …).
- Cookie: `HttpOnly`, `SameSite=Lax`, `Secure` cuando hay HTTPS
  (`SESSION_COOKIE_SECURE=1`).
- Vencimiento de sesión: 8 horas (`FERREGEST_SESSION_HOURS`).
- **Límite de intentos persistente** (ARQ-08): 8 fallidos en 60 minutos →
  bloqueo temporal de 15 minutos, contado en la tabla `login_attempts`
  (sobrevive al reinicio y se comparte entre workers).
- Cierre de sesión por **POST con CSRF** (ARQ-10): un `<img src="/logout">` ya
  no puede desconectar a la usuaria.

## 3. Autorización

- Decoradores `login_required` y `permission_required(perm)`; 19 permisos
  gestionables por usuario.
- Toda acción crítica se valida **en el servidor** (no se ocultan sólo botones):
  descuentos, stock negativo, anulación, devoluciones, cierre de caja,
  verificación de transferencias, cambios de precio, licencias, configuración.
- Rutas privadas sin sesión → 302 al login; rutas `/api/*` → 401.

## 4. CSRF

- Token aleatorio por sesión (16 bytes), en `meta` y en campo `_csrf`.
- Validado en **todo** POST/PUT/PATCH/DELETE con `secrets.compare_digest`.
- Falta o error de token → 400.
- El logout y el cambio de contraseña también están protegidos.

## 5. Inyecciones y XSS

- Consultas SQL siempre con parámetros (`?`): probado con
  `'; DROP TABLE products;--` en los buscadores (la tabla queda intacta).
- **XSS almacenado corregido (ARQ-01)**: ningún dato de la base llega al DOM
  por `innerHTML`. Se usan `textContent` y los helpers `el()` / `escapeHtml()`.
  Arnés automático en `tests/js/xss_harness.js` (16 comprobaciones) más prueba
  de regresión en el backend.
- Cabeceras de seguridad (ARQ-14): CSP, `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` y
  `Cache-Control: no-store` en páginas autenticadas.
- Sin redirección abierta (ARQ-13): `?next=` sólo acepta rutas internas.

## 6. Validación de entradas

- Importes, cantidades y descuentos se recalculan **en el servidor** con
  `Decimal` (ARQ-09); el navegador no impone precios.
- Carga de archivos: límite de 16 MB, validación de extensión, columnas y
  valores; los importadores no ejecutan contenido del archivo.
- La suma de los pagos debe coincidir con el total; se valida stock, unidades
  habilitadas, límites de crédito y estados (venta activa, caja abierta).

## 7. Registro y auditoría

- Tabla `audit_log` con usuario, acción, entidad, id y detalle (diff
  anterior/nuevo cuando aplica).
- Se registran: logins (exitosos y fallidos), bloqueos, altas y cambios de
  productos, precios, ventas, anulaciones, devoluciones, cobros, pagos a
  proveedores, movimientos y cierres de caja, transferencias, licencias y
  cambios de configuración.
- **Nunca** se registran contraseñas.

## 8. Datos y disponibilidad

- La suspensión por licencia **no** borra ni bloquea la lectura: se pueden ver
  informes, exportar y respaldar (ver `docs/LICENCIAS.md`).
- Copias de seguridad en `docs/OPERACION_Y_BACKUP.md`, con procedimiento de
  restauración verificado.
- Migraciones transaccionales con copia previa (ARQ-11).

## 9. Límites aceptados y próximos pasos

| Límite | Mitigación actual | Próximo paso recomendado |
|---|---|---|
| CSP con `'unsafe-inline'` | Los datos no se interpolan en HTML | Migrar a nonces o scripts externos |
| Columnas monetarias `REAL` | Cálculo en `Decimal`, cuantizado antes de persistir | Migración futura a enteros en centavos |
| SQLite: un escritor a la vez | WAL + `busy_timeout` 8 s + `BEGIN IMMEDIATE` | Evaluar otro motor sólo si crece la concurrencia |
| Sin 2FA / recuperación de clave | Restauración por administrador de la instalación | Documentar procedimiento interno y resguardo de la clave inicial |
| Sin HTTPS incluido | `SESSION_COOKIE_SECURE=1` cuando se sirve por HTTPS | Proxy local con certificado si se accede desde otros equipos |

## 10. Checklist antes de publicar en GitHub

- [x] `python3 tools/check_repo.py` → `CONTINUE`
- [x] Sin `.secret`, `.db`, `.license_key`, `.env`, respaldos ni exportaciones
- [x] `.gitignore` ampliado y verificado
- [x] 45 pruebas en verde (`python3 -m pytest tests/ -v`)
- [x] Arnés XSS en verde (`node tests/js/xss_harness.js`)
- [x] Documentación técnica y de seguridad actualizada
