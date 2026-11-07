# Manual de uso — FerreGest AR

Dirigido a: propietarios, vendedores y encargados de depósito.

## 1. Ingreso

1. Abra la dirección del sistema en el navegador (computadora, tablet o celular).
2. Ingrese usuario y contraseña. Cada persona usa el **suyo** (nunca compartir).

## 2. Panel principal

Muestra: ventas de hoy y del mes, ganancia (si tiene permiso), stock bajo,
transferencias por verificar, valor del stock, cuentas por cobrar/pagar,
gráfico de 7 días, estado de caja y últimas ventas.

La barra superior tiene un **buscador global**: escriba parte de un nombre,
código o código de barras.

## 3. Punto de venta (POS)

1. **Busque** el producto escribiendo nombre/código o **escanee** el código de
   barras (el lector actúa como teclado: al presionar Enter se agrega solo).
2. Ajuste en el carrito: **unidad de venta** (unidad, metro, caja, rollo…),
   **cantidad fraccionada** (ej.: `2,5`), **precio** y **descuento** (si tiene
   permiso).
3. Elija **cliente** (obligatorio si pagará a cuenta corriente) y, si quiere,
   agregue notas.
4. Revise **Subtotal / Descuentos / Impuestos / Total** (calculados en el
   servidor con la configuración fiscal vigente).
5. Seleccione el/los **medios de pago**:
   - Efectivo, Débito, Crédito, Cuenta corriente, **Transferencia**.
   - Para **pagos mixtos**: marque varios medios e importes que sumen el total.
   - **Transferencia**: complete banco/entidad, referencia y si el cliente
     informó que ya la hizo. Quedará **PENDIENTE de verificación** (nadie la
     acredita automáticamente).
6. **Cobrar y emitir comprobante**: se registra la venta, descuenta stock,
   genera el movimiento y abre el comprobante interno (imprimible).
   - ✕ La facturación electrónica fiscal **no está simulada**: el comprobante
     dice claramente que es interno de gestión.

## 4. Ventas y devoluciones

- **Ventas**: historial con filtros por fecha, estado y texto. Click en el Nº
  para ver el detalle, imprimir el comprobante o **anular** (con motivo y
  permiso; repone stock y revierte pagos).
- **Devolución**: en la venta, «Devolución» → indique renglones y cantidades.
  Repone el stock y registra el egreso (efectivo) o el acredito (cuenta
  corriente) correspondiente.

## 5. Transferencias

Menú **Transferencias**: lista por estado (pendiente / informada / verificada /
rechazada). **Solo administradores con permiso** verifican o rechazan cargando
un comentario. Mientras esté pendiente, la venta figura como
`pendiente_transferencia`.

## 6. Productos e inventario

- **Productos**: alta con código, barras, marca, categoría, proveedor,
  **unidad base**, precios (compra/venta/mayorista/especial), stock mínimo,
  ubicación y **conversiones por producto** (ej.: 1 rollo = 100 metros).
- **Carga masiva** (Productos → Carga masiva): suba un **CSV o Excel (.xlsx)**
  con columnas `Codigo, Descripcion, Marca, Unidad, Precio compra, Precio venta,
  Stock minimo, Cantidad` (acepta `3.000,50`). Opcional `accion_stock` =
  `sumar` (entra mercadería) o `reemplazar` (conteo físico) para productos ya
  existentes: el stock se actualiza **con movimiento auditado**, nunca a mano.
- **Movimientos**: bitácora completa (fecha, tipo, cantidad, stock resultante,
  usuario, motivo). Los ajustes manuales (conteo, rotura, pérdida) exigen motivo.
- **Alertas**: bajo mínimo, sin existencias, sin movimiento en 90 días y
  rotación de 30 días.

## 7. Compras

1. **+ Nueva orden de compra**: proveedor, condición de pago, renglones
   (haga clic en el producto para agregarlo) y guarde.
2. Al llegar la mercadería: **Registrar recepción** (parcial o total). El
   stock entra automáticamente y el **costo promedio se recalcula** con el
   ponderado; el historial de precios queda auditado.
3. En la ficha del proveedor se registran pagos y se ve la cuenta corriente.

## 8. Clientes y cuentas corrientes

Ficha del cliente: datos, límite de crédito, ventas, cobros y **estado de
cuenta** (debe/haber). Los cobros por transferencia quedan **pendientes de
verificación** hasta que un administrador los confirme.

## 9. Caja

- **Abrir caja** con el saldo inicial del día.
- Los cobros en efectivo de las ventas entran solos;también puede registrar
  ingresos/egresos manualmente con concepto.
- **Gastos** (alquiler, servicios…) se descuentan de la caja si está abierta.
- **Cerrar caja**: ingrese el efectivo contado → el sistema calcula esperado y
  **diferencia**. El historial guarda todos los arqueos.

## 10. Informes

Pestañas: Ventas (día, vendedor, medio de pago), Productos y stock,
Rentabilidad (margen por categoría/producto), Cuentas (cobrar/pagar +
transferencias pendientes) y Caja (flujo diario). Exportación **CSV** y **Excel**.

## 11. Dudas frecuentes

- **«No puedo aplicar un descuento»** → su rol no tiene el permiso; pida al
  administrador.
- **«La venta quedó en rojo (pendiente de transferencia)»** → es correcto: un
  administrador debe verificarla en el menú Transferencias.
- **«El total no coincide con lo que esperaba»** → revise impuestos activos
  en Configuración (el cálculo es centralizado y auditable por renglón).
