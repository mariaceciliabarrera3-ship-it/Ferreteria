# Sistema de licenciamiento — FerreGest AR

## Modelo

- **Instalaciones independientes**: cada ferretería tiene su propia base de
  datos y usuarios. **No existe base compartida ni multitenant**: los datos de
  distintos comercios no pueden mezclarse.
- **Licencia controlada por la propietaria del producto**: cada instalación
  recibe una licencia firmada criptográficamente.

## Componentes

| Componente | Dónde vive | Función |
|---|---|---|
| `install_id` | En la instalación (`FER-…`) | Identifica al comercio sin enviarle datos |
| Licencia firmada | Archivo de texto entregado al cliente | Payload + HMAC-SHA256 |
| `app/license.py` | Instalación | Verificación **local**, sin llamadas externas |
| `tools/panel_licencias.py` | **Solo la propietaria** | Emite/renueva licencias firmadas |

## Estados y transiciones

```
activa ──(≤15 días para el vencimiento)──▶ por_vencer (aviso en pantalla)
   │
   └──(vencimiento)──▶ vencida_gracia (gracia configurable, ej. 7 días, operando)
                            │
                            └──(fin de gracia)──▶ SUSPENDIDA
                                     │                 │
                        (licencia nueva importada)     │
                                     ▼                 │
                                REACTIVADA ◀────────────┘  (los datos jamás se borran)
```

Al estar **suspendida**:
- ✗ No se registran ventas, compras, movimientos de caja ni cambios de stock.
- ✓ Se puede consultar todo, ver informes, **exportar datos** y hacer backups.
- ✓ Los datos permanecen íntegros (verificado por la prueba 9).

## Flujo comercial

1. La propietaria crea la instalación (el cliente envía su `install_id`
   desde el menú Licencia).
2. Emite la licencia:
   ```bash
   export LICENSE_SIGNING_KEY="…"      # secreto, NUNCA en el repo
   python3 tools/panel_licencias.py crear \
        --instalacion FER-XXXX --cliente "Ferretería Z" --dias 365
   ```
   El registro local `tools/licencias_emitidas.jsonl` guarda el historial de
   emisiones (renovaciones, montos y fechas — su control comercial).
3. El cliente pega el archivo en **Licencias → Importar**.
4. Al vencer, la instalación avisa, otorga gracia y suspende automáticamente.
5. Tras el pago, se emite una licencia nueva y se reactiva (misma base).

## Privacidad

- La verificación es **100 % local**: no se envían ventas, clientes,
  proveedores, montos ni movimientos a ningún servidor de la propietaria.
- La licencia solo contiene: ID de licencia, ID de instalación, cliente,
  fechas y estado.
- No hay mecanismos ocultos, destruidos ni de acceso remoto.

## Nota de seguridad de la clave

`LICENSE_SIGNING_KEY` debe guardarse como secreto de la propietaria
(gestor de contraseñas). Si se filtra, podría emitirse licencias falsas; si
se pierde, se emiten nuevas con una clave nueva y se re-importan.
