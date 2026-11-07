"""FerreGest AR — aritmética monetaria y de cantidades (ARQ-09).

Regla del proyecto: **el dinero nunca se acumula en ``float``**.

- Todo importe que entra (formulario, JSON, columna SQLite ``REAL``, texto con
  coma o punto decimal) se convierte a ``decimal.Decimal`` con :func:`D`.
- Toda suma, resta, multiplicación por cantidad y reparto proporcional se hace
  en ``Decimal`` y se redondea una única vez, al final de cada renglón, con
  ``ROUND_HALF_UP`` (criterio comercial argentino: 0,005 -> 0,01).
- Sólo al escribir en SQLite se convierte a ``float`` (:func:`f2`), porque la
  columna es ``REAL``. Ese ``float`` ya está cuantizado a 2 decimales, por lo
  que no arrastra error binario acumulado.

Esto corrige dos defectos del esquema anterior:
1. ``round(2.675, 2)`` daba ``2.67`` (redondeo bancario + error binario).
2. Sumar cientos de renglones en ``float`` desplazaba centavos.

Las cantidades (stock, metros, kilos) usan 4 decimales (:func:`q4`).
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable

__all__ = ["D", "q2", "q4", "f2", "f4", "sum_q2", "money_str", "EPS"]

#: Precisión monetaria: 2 decimales.
CENT = Decimal("0.01")
#: Precisión de cantidades: 4 decimales.
TEN_THOUSANDTH = Decimal("0.0001")
#: Tolerancia para comparaciones de dinero (medio centavo).
EPS = Decimal("0.005")

_ZERO = Decimal("0")


def D(x, default: Decimal = _ZERO) -> Decimal:
    """Convierte ``x`` a ``Decimal`` de forma segura.

    Acepta ``Decimal``, ``int``, ``float``, ``str`` (con ``.`` o ``,``) y
    ``None``. Nunca lanza: si no se puede interpretar devuelve ``default``.
    """
    if x is None:
        return default
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        return default
    if isinstance(x, float):
        # str() evita arrastrar el error binario del float (0.1 -> 0.1000000000000000055)
        try:
            return Decimal(str(x))
        except InvalidOperation:
            return default
    if isinstance(x, int):
        return Decimal(x)
    s = str(x).strip().replace(" ", "")
    if not s:
        return default
    # Formato argentino: 1.234,56 -> 1234.56 ; también acepta 1234.56
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):      # 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:                                 # 1,234.56
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return default


def q2(x) -> Decimal:
    """Cuantiza a 2 decimales con redondeo comercial (HALF_UP)."""
    return D(x).quantize(CENT, rounding=ROUND_HALF_UP)


def q4(x) -> Decimal:
    """Cuantiza a 4 decimales (cantidades) con redondeo HALF_UP."""
    return D(x).quantize(TEN_THOUSANDTH, rounding=ROUND_HALF_UP)


def f2(x) -> float:
    """Importe listo para persistir en columna REAL (ya redondeado)."""
    return float(q2(x))


def f4(x) -> float:
    """Cantidad lista para persistir en columna REAL (4 decimales)."""
    return float(q4(x))


def sum_q2(values: Iterable) -> Decimal:
    """Suma una iterable de importes y devuelve el total cuantizado a 2 decimales."""
    total = _ZERO
    for v in values:
        total += D(v)
    return q2(total)


def money_str(x) -> str:
    """Importe en formato argentino para mensajes de error / tickets."""
    v = q2(x)
    s = f"{abs(v):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return ("-$ " if v < 0 else "$ ") + s
