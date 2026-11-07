# Manual de administración — FerreGest AR

## 1. Configuración del negocio

Menú **Configuración** (solo administradores):

| Pestaña | Qué se configura |
|---|---|
| 🏪 Negocio | Nombre, dirección, CUIT, condición de IVA, pie y nota legal del comprobante |
| 🧾 Impuestos | Conceptos fiscales (nombre, alícuota, incluido/agregado, alcance global/categoría/producto, vigencias), activar/desactivar e historial de cambios |
| 🗂 Categorías | Altas de categorías (rubros) |
| 📐 Unidades | Unidades de medida disponibles (unidad, metro, caja, rollo, kilo, litro, bolsa, juego…) |
| 🏦 Transferencias | Cuentas de destino (banco, alias, CBU, titular) que se ofrecen al cobrar |
| 💳 Medios de pago | Qué medios aparecen habilitados en el POS |

### Impuestos (configuración fiscal)

- **Ningún impuesto viene activado.** El administrador crea y activa los que
  correspondan a su situación.
- Cada concepto define: nombre, alícuota (%), si se **agrega** al precio o está
  **incluido**, alcance (todos los productos / una categoría / un producto) y
  vigencia.
- **Regla del sistema**: el comprobante interno **no es factura electrónica**.
  Ante ARCA no se simula autorización, CAI, RG ni sellos. Si necesita facturar
  electrónicamente, use el sistema en modo gestión interna junto con su
  contador o el servicio oficial correspondiente.
- **Aviso permanente**: la configuración de alícuotas y percepciones debe
  validarse con un profesional matriculado antes de usarse para obligaciones
  fiscales. El sistema informa esto y no declara configuraciones como
  legalmente correctas.
- Toda modificación queda en **historial** (valores anterior/nuevo, usuario,
  fecha) y **nunca altera ventas históricas** (sus importes están congelados
  por renglón).

## 2. Usuarios y permisos

Menú **Usuarios**. Roles predefinidos: `administrador`, `vendedor`, `stock`,
`administrativo`. Por usuario se marcan permisos individuales:

`pos.operar`, `productos.gestionar`, `precios.modificar`, `descuentos.aplicar`,
`ventas.anular`, `stock.modificar`, `stock.negativo`, `compras.gestionar`,
`caja.operar`, `caja.cerrar`, `transferencias.verificar`, `clientes.gestionar`,
`cuentas.consultar`, `compras.consultar`, `reportes.ganancias`,
`configuracion.gestionar`, `usuarios.gestionar`, `licencias.gestionar`,
`auditoria.consultar`.

Ejemplos:
- Vendedor sin permiso de precios → no puede editar la ficha de precios.
- Solo `ventas.anular` anula ventas (con motivo obligatorio).
- Solo `transferencias.verificar` confirma transferencias.
- `stock.negativo` es la autorización expresa del administrador para dejar
  stock negativo en una venta puntual.
- Contraseñas: mínimo 8 caracteres, almacenadas con hash (scrypt/pbkdf2 de
  Werkzeug), nunca en texto plano ni en el código.

## 3. Auditoría

Menú **Auditoría**: quién, qué, cuándo y detalle (con valores anterior/nuevo)
de logins, ventas, anulaciones, devoluciones, altas/ediciones de productos,
cambios de precio, compras, recepciones, movimientos de caja, cobros,
cambios de impuestos, usuarios, configuración e importación de licencias.

## 4. Licencia

Menú **Licencia**: estado (activa / por vencer / gracia / suspendida /
reactivada), ID de instalación, vencimiento, importación de licencia firmada y
**exportación de datos** (disponible siempre, también suspendida).
Detalle completo en `LICENCIAS.md`.

## 5. Copias de seguridad

- Diario: `python3 tools/backup.py` (ver `DESPLIEGUE.md`).
- Desde la interfaz: **Licencias → Exportar datos (JSON)**.
- Restauración: reemplazar `ferregest.db` con la app detenida.

## 6. Operación diaria recomendada

1. Abrir caja con el saldo inicial.
2. Ventas por POS; verificar transferencias informadas a la mañana.
3. Registrar recepción de mercadería apenas llegue (el stock y el costo se
   actualizan solos).
4. Revisar **Alertas de stock** y pedir reposición.
5. Al cerrar: gastos del día y cierre de caja con arqueo.
6. Semanal: informes de rentabilidad y cuentas por cobrar/pagar.
