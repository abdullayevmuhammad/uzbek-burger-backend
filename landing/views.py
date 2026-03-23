from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils.text import slugify

from core.models import Branch
from menu.models import Food, FoodType

from .models import LandingSettings, Post


PUBLIC_FOOD_TYPE_SLUGS = {
    "fastfood": FoodType.FASTFOOD,
    "drink": FoodType.DRINK,
    "set": FoodType.SET,
}
PUBLIC_FOOD_TYPE_VALUES = {value: slug for slug, value in PUBLIC_FOOD_TYPE_SLUGS.items()}


def _common_context(active_page: str):
    settings = LandingSettings.objects.first()
    return {"settings": settings, "active_page": active_page}


def _normalize_public_food_type(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return ""

    upper_value = value.upper()
    if upper_value in PUBLIC_FOOD_TYPE_VALUES:
        return upper_value
    return PUBLIC_FOOD_TYPE_SLUGS.get(value.lower(), "")


def _menu_foods_queryset():
    return (
        Food.objects.filter(is_active=True).filter(Q(branch__isnull=True) | Q(branch__is_active=True))
        .select_related("category", "branch")
        .annotate(
            type_priority=Case(
                When(type=FoodType.FASTFOOD, then=Value(1)),
                When(type=FoodType.DRINK, then=Value(2)),
                When(type=FoodType.SET, then=Value(3)),
                default=Value(99),
                output_field=IntegerField(),
            )
        )
        .order_by("type_priority", "category__sort_order", "sort_order", "name")
    )


def _build_category_options(foods_qs):
    seen_slugs = set()
    options = []

    for category_name in foods_qs.exclude(category__name__isnull=True).values_list("category__name", flat=True):
        if not category_name:
            continue
        slug = slugify(category_name)
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        options.append({"slug": slug, "name": category_name})

    options.sort(key=lambda item: item["name"].lower())
    return options


def _build_menu_context(*, q: str = "", type_param: str = "", category_param: str = ""):
    type_value = _normalize_public_food_type(type_param)
    type_slug = PUBLIC_FOOD_TYPE_VALUES.get(type_value, "")
    base_qs = _menu_foods_queryset()

    filterable_qs = base_qs.filter(type=type_value) if type_value else base_qs
    available_categories = _build_category_options(filterable_qs)
    category_lookup = {option["slug"]: option["name"] for option in available_categories}

    category_slug = (category_param or "").strip()
    category_name = category_lookup.get(category_slug, "")

    foods = filterable_qs
    if category_name:
        foods = foods.filter(category__name__iexact=category_name)

    if q:
        foods = foods.filter(
            Q(name__icontains=q)
            | Q(category__name__icontains=q)
            | Q(branch__name__icontains=q)
        )

    foods = list(foods)

    return {
        "foods": foods,
        "q": q,
        "type": type_slug,
        "selected_type": type_value,
        "category": category_slug if category_name else "",
        "selected_category_name": category_name,
        "available_categories": available_categories,
        "result_count": len(foods),
    }


def home(request):
    ctx = _common_context("home")

    # Oxirgi yangiliklar
    ctx["posts"] = (
        Post.objects.filter(is_published=True)
        .order_by("-published_at", "-created_at")[:3]
    )

    # Menudan preview (ko'p bo'lsa ham faqat bir nechta ko'rsatamiz)
    foods_qs = _menu_foods_queryset()
    ctx["foods"] = foods_qs[:8]

    # Landingda ko'rinadigan filiallar
    ctx["branches"] = (
        Branch.objects.filter(is_active=True, show_on_landing=True)
        .order_by("name")[:6]
    )

    return render(request, "landing/index.html", ctx)


def about(request):
    ctx = _common_context("about")
    return render(request, "landing/about.html", ctx)


def menu(request):
    ctx = _common_context("menu")

    q = (request.GET.get("q") or "").strip()
    type_param = (request.GET.get("type") or "").strip()
    category_param = (request.GET.get("category") or "").strip()

    ctx.update(_build_menu_context(q=q, type_param=type_param, category_param=category_param))

    return render(request, "landing/menu.html", ctx)


def menu_live(request):
    q = (request.GET.get("q") or "").strip()
    type_param = (request.GET.get("type") or "").strip()
    category_param = (request.GET.get("category") or "").strip()
    panel_context = _build_menu_context(q=q, type_param=type_param, category_param=category_param)
    panel_context.update(_common_context("menu"))

    html = render_to_string("landing/partials/menu_panel.html", panel_context, request=request)
    return JsonResponse(
        {
            "ok": True,
            "html": html,
            "count": panel_context["result_count"],
            "type": panel_context["type"],
            "category": panel_context["category"],
            "query": panel_context["q"],
        }
    )


def branches(request):
    ctx = _common_context("branches")
    branches_qs = Branch.objects.filter(is_active=True, show_on_landing=True).order_by("name")
    branches_list = list(branches_qs)
    ctx["branches"] = branches_list
    ctx["selected_branch"] = branches_list[0] if branches_list else None
    return render(request, "landing/branches.html", ctx)


def posts_list(request):
    ctx = _common_context("posts")

    qs = Post.objects.filter(is_published=True).order_by("-published_at", "-created_at")
    paginator = Paginator(qs, 8)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    ctx["page_obj"] = page_obj
    ctx["posts"] = page_obj.object_list
    return render(request, "landing/posts.html", ctx)


def post_detail(request, slug):
    ctx = _common_context("posts")
    post = get_object_or_404(Post, slug=slug, is_published=True)
    return render(request, "landing/post_detail.html", {**ctx, "post": post})


def contact(request):
    ctx = _common_context("contact")
    return render(request, "landing/contact.html", ctx)
