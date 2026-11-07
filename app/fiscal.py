"""FerreGest AR — motor fiscal y de precios centralizado.

Todos los cálculos de impuestos y rentabilidad pasan por este módulo para que
todas las pantallas sean consistentes.

Principios:
- Los impuestos NO vienen activados: cada concepto se configura y activa
  opcionalmente por el administrador.
- Al crear una venta se guarda un *snapshot* del cálculo por renglón
  (tax_breakdown). Cambiar la configuración futura nunca altera históricos.
- Alícuotas, nombres y reglas las define el administrador; el sistema no
  asume que ningún esquema es el legalmente correcto y muestra el recordatorio
  de validación profesional.
"""
from datetime import date
from decimal import Decimal

from .db import query
from .money import D, f2, q2


def _in_vigencia(row, when: str | None) -> bool:
    d = (when or "")[:10]
    if row["valid_from"] and d and d < row["valid_from"]:
        return False
    if row["valid_to"] and d and d > row["valid_to"]:
        return False
    return True


def applicable_taxes(product, when: str | None = None) -> list[dict]:
    """Impuestos vigentes y activos que aplican a un producto (snapshot dict)."""
    rows = query(
        "SELECT * FROM taxes WHERE active = 1 AND ("
        " scope = 'global'"
        " OR (scope = 'categoria' AND category_id IS NOT NULL AND category_id = ?)"
        " OR (scope = 'producto' AND product_id IS NOT NULL AND product_id = ?)"
        ")",
        (product["category_id"], product["id"]),
    )
    out = []
    for r in rows:
        if not _in_vigencia(r, when):
            continue
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "rate": float(r["rate"]),
                "mode": r["mode"],
            }
        )
    # Un producto con impuesto propio explícito usa además su tax_id si coincide?
    # Regla documentada: el impuesto asignado directamente al producto se aplica
    # además de los de alcance 'global'. (scope='producto' ya lo cubre.)
    return out


def compute_line_taxes(unit_price: float, qty: float, discount: float, taxes: list[dict]) -> dict:
    """Calcula impuestos de un renglón.

    - mode 'agregado': se suma al total (base = neto).
    - mode 'incluido': el importe ya forma parte del precio (se extrae para
      informarlo, no aumenta el total).
    Devuelve: {'breakdown': [...], 'tax_amount': X (agregados), 'included': Y}
    """
    # ARQ-09: todo el cálculo se hace en Decimal y se redondea una sola vez
    # por renglón con criterio comercial (0,005 -> 0,01).
    base = q2(D(unit_price) * D(qty) - D(discount))
    agregado = Decimal("0")
    incluido = Decimal("0")
    breakdown = []
    for t in taxes:
        rate = D(t["rate"])
        if t["mode"] == "incluido":
            amount = q2(base * rate / (100 + rate)) if (100 + rate) else Decimal("0")
            incluido = q2(incluido + amount)
        else:
            amount = q2(base * rate / 100)
            agregado = q2(agregado + amount)
        breakdown.append(
            {"name": t["name"], "rate": float(rate), "mode": t["mode"],
             "amount": float(amount)}
        )
    return {"breakdown": breakdown, "tax_amount": float(agregado),
            "included": float(incluido), "base": float(base)}


def margin_pct(cost: float, price: float) -> float:
    cost = float(cost or 0)
    price = float(price or 0)
    if cost <= 0:
        return 0.0
    return float(q2((D(price) - D(cost)) / D(cost) * 100))


def price_history_save(product_id, field, old, new, user_id, note=""):
    # ARQ-09: comparación y guardado con redondeo decimal (sin float).
    if q2(old) == q2(new):
        return
    from .db import insert

    insert(
        "INSERT INTO price_history (product_id, field, old_value, new_value, user_id, changed_at, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (product_id, field, float(q2(old)), float(q2(new)), user_id, now_iso_import(), note),
    )


def now_iso_import():
    from .db import now_iso

    return now_iso()


def stock_valuation() -> dict:
    """Valor del stock existente a costo y a precio de venta."""
    row = query(
        "SELECT COALESCE(SUM(stock * avg_cost),0) AS cost, "
        "COALESCE(SUM(stock * sale_price),0) AS retail, "
        "COALESCE(SUM(CASE WHEN stock > 0 THEN 1 ELSE 0 END),0) AS con_stock "
        "FROM products WHERE active = 1",
        one=True,
    )
    return {"cost": float(q2(row["cost"])), "retail": float(q2(row["retail"])),
            "items_count": row["con_stock"]}


def sales_profit(since: str, until: str) -> dict:
    """Ganancia estimada = (total - costo de mercadería) de ventas activas."""
    r = query(
        "SELECT COALESCE(SUM(total),0) AS total, COALESCE(SUM(cost_total),0) AS cost, "
        "COALESCE(SUM(discount),0) AS disc, COUNT(*) AS n "
        "FROM sales WHERE status = 'activa' AND substr(datetime,1,10) BETWEEN ? AND ?",
        (since, until),
        one=True,
    )
    total_v = D(r["total"])
    cost_v = D(r["cost"])
    profit = q2(total_v - cost_v)
    return {
        "sales": float(q2(total_v)),
        "cost": float(q2(cost_v)),
        "profit": float(profit),
        "discounts": float(q2(r["disc"])),
        "count": r["n"],
        "margin": float(q2(profit / total_v * 100)) if total_v else 0.0,
    }
