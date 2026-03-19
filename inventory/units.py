from decimal import Decimal

BASE_FACTOR = {
    "pcs": Decimal("1"),
    "kg": Decimal("1000"),
    "gr": Decimal("1"),
    "l": Decimal("1000"),
    "ml": Decimal("1"),
}


def to_base(qty: Decimal, count_type: str) -> Decimal:
    """
    Convert a quantity to canonical base units.
    kg -> gr, l -> ml, pcs -> pcs.
    """
    if qty is None:
        return Decimal("0")
    factor = BASE_FACTOR.get(count_type, Decimal("1"))
    return (Decimal(qty) * factor)


def from_base(qty_base: Decimal, count_type: str) -> Decimal:
    """
    Convert a base quantity back to the product's declared unit.
    """
    factor = BASE_FACTOR.get(count_type, Decimal("1"))
    if factor == 0:
        return Decimal("0")
    return Decimal(qty_base) / factor
