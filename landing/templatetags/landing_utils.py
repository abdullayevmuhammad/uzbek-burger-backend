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
    """Narxni '12 500 so'm' ko'rinishida chiqaradi."""
    if value is None or value == "":
        return "0 so'm"
    try:
        n = int(value)
    except Exception:
        return f"{value} so'm"
    return f"{_group_int(n)} so'm"
