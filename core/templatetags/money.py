from django import template

register = template.Library()

def _group_int(n: int) -> str:
    s = str(abs(int(n)))
    parts = []
    while s:
        parts.append(s[-3:])
        s = s[:-3]
    out = " ".join(reversed(parts)) or "0"
    return f"-{out}" if int(n) < 0 else out

@register.filter
def som(value):
    if value is None or value == "":
        return "0 so‘m"
    try:
        n = int(value)
    except Exception:
        return f"{value} so‘m"
    return f"{_group_int(n)} so‘m"


from decimal import Decimal, InvalidOperation

@register.filter
def qty(value):
    """
    Decimal miqdor:
      1000.000 -> '1 000'
      12.500 -> '12,5'
      12.2500 -> '12,25'
    """
    if value is None or value == "":
        return "0"
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)

    # kasr qismi 0 bo'lsa - butun qilib qaytaramiz
    if d == d.to_integral_value():
        n = int(d)
        s = str(abs(n))
        parts = []
        while s:
            parts.append(s[-3:])
            s = s[:-3]
        out = " ".join(reversed(parts)) or "0"
        return f"-{out}" if n < 0 else out

    # kasr bo'lsa: trailing 0 larni olib tashlaymiz, '.' -> ','
    s = format(d.normalize(), "f")  # '12.5', '12.25'
    if "." in s:
        a, b = s.split(".", 1)
        b = b.rstrip("0")
        s = a if not b else f"{a},{b}"
    # butun qismni 3 xonadan guruhlaymiz
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    a, *rest = s.split(",", 1)
    parts = []
    aa = a
    while aa:
        parts.append(aa[-3:])
        aa = aa[:-3]
    a_grouped = " ".join(reversed(parts)) or "0"
    s2 = a_grouped + ("," + rest[0] if rest else "")
    return "-" + s2 if neg else s2
