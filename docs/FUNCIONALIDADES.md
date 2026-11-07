# Funcionalidades — estado real

## ✅ Terminadas y verificadas (con prueba o demostración)

**Productos e inventario**
- Alta/edición con código, barras, marca, modelo, categoría (con campo
  `parent_id` preparado para subcategorías), proveedor, ubicación,
  observaciones, estado activo/inactivo.
- Unidades de medida libres (alta desde Configuración) y **conversiones
  configurables por producto** (1 rollo = 100 m, 1 bolsa = 50 kg…).
- Cantidades decimales en todo el sistema (2,75 metros).
- Precios: compra, venta, mayorista, especial + **historial de cambios** con
  usuario y fecha; costo de reposición vs costo histórico (promedio ponderado).
- Stock mínimo/máximo, alertas (bajo mínimo, sin stock, sin movimiento 90 días,
  rotación 30 días), valorización a costo y a precio de venta.
- Movimientos auditables (tipo, cantidad, stock resultante, usuario, motivo,
  referencia); imposible cambiar stock sin dejar registro.
- **Carga masiva de stock sin cargar uno a uno**: importación CSV y **Excel (.xlsx)** con números en formato argentino, acciones sumar/reemplazar por fila y **movimiento auditable obligatorio** (inventario inicial, entrada o ajuste de conteo). Exportación CSV.

**Ventas (POS)**
- Búsqueda/escaneo de código de barras, carrito, unidades por renglón,
  cantidades fraccionadas, precios editables, descuentos con permiso.
- Cálculo centralizado en servidor (subtotal, descuentos, impuestos, total).
- Medios de pago: efectivo, transferencia, débito, crédito, cuenta corriente y
  **pagos mixtos**.
- **Transferencias como medio de primera clase**: banco, CBU/alias de destino
  (configurable), importe, referencia, cliente, venta, estados
  pendiente → informada → verificada/rechazada con **verificación manual**
  y auditoría. Nunca se acreditan automáticamente.
- Comprobante interno imprimible (con aviso de no-factura fiscal).
- Anulación con motivo (repone stock, revierte caja/libro) y **devoluciones**
  parciales con reembolso a efectivo / cuenta corriente / registro transferencia.
- Historial de ventas con filtros y exportación.

**Compras y proveedores**
- Proveedores con datos fiscales, contactos, condiciones de pago.
- Órdenes de compra, **recepción parcial o total** que actualiza stock y
  recalcula costo promedio; estados pendiente/parcial/recibida; historial de
  precios de proveedor.
- Pagos a proveedor con libro (debe/haber) y egreso de caja.

**Caja y administración**
- Apertura con saldo inicial, ingresos/egresos, gastos con categoría,
  cierre con arqueo (esperado/contado/diferencia), historial.
- Gastos independientes de caja (o descontados de la sesión abierta).

**Clientes y cuentas corrientes**
- Altas con CUIT/DNI, límite de crédito (bloqueo server-side + excedentes solo
  admin), estado de cuenta imprimible (debe/haber), cobros (efectivo, débito,
  crédito, transferencia pendiente de verificación).

**Fiscal (Argentina)**
- Configuración voluntary de conceptos (nombre, alícuota, incluido/agregado,
  alcance, vigencias), activar/desactivar, **historial de cambios**.
- Impuestos desactivados por defecto; snapshots por renglón → históricos
  inalterables. Aviso de validación profesional. Preparación para ARCA
  **documentada, no simulada**.

**Administración**
- Negocio (nombre, logo/datos, CUIT, condición IVA, pie de ticket), unidades,
  categorías, medios de pago, cuentas de transferencia.
- Usuarios con 4 roles + **19 permisos granulares**; auditoría completa.
- Licenciamiento por instalación (estados completos + exportación siempre
  disponible) y panel central CLI de la propietaria.
- Informes reales (ventas por día/vendedor/medio, top/menos vendidos,
  rentabilidad por categoría/producto, stock valorizado, cuentas, flujo de
  caja) con exportación CSV y **Excel real (openpyxl)**.
- Copia de seguridad CLI + exportación JSON desde la UI.

## ⏳ Pendientes / futuras (sin simulación)

- Integración **real** con servicios de facturación electrónica de ARCA
  (arquitectura preparada: módulo fiscal parametrizable; requiere
  habilitación oficial y probablemente datos/CAI del comercio).
- Notas de crédito fiscales numeradas (hoy: devolución interna con numeración
  `NC-` propia, no es documento fiscal).
- Depósitos múltiples y transferencias internas entre depósitos.
- Listas de precios múltiples con vigencias (hoy: venta/mayorista/especial).
- PDF nativo de comprobantes (hoy: impresión del HTML del comprobante, que
  cubre impresora térmica y A4 vía CSS `@media print`).
- Recibo de dinero/cheque en pago de cuenta corriente (transferencia y
  efectivo sí implementados).
- 2FA y rate limit distribuido (ver INFORME_SEGURIDAD §10).

## ❌ Descartadas con justificación

- Facturación electrónica simulada → **prohibida por el pliego**.
- Integración bancaria automática de transferencias → **prohibida** (sin
  servicios pagos; se implementa verificación manual).
- Multitenant con base compartida → **prohibido** por el modelo de negocio.
- Copiar código de los repos de partida → **sin licencia** (copyright
  por defecto); se estudiaron solo ideas y flujos (ver AUDITORIA_REPOSITORIOS.md).
