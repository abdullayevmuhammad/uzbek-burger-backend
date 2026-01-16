from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """
    URL query stringni oson yangilash:
    <a href="{% qs o='name' %}">...</a>
    """
    request = context["request"]
    q = request.GET.copy()
    for k, v in kwargs.items():
        if v is None:
            q.pop(k, None)
        else:
            q[k] = v
    s = q.urlencode()
    return f"?{s}" if s else ""
