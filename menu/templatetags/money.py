from django import template

register = template.Library()

@register.filter
def money(value):
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return value
    return f"{n:,}".replace(",", " ")
