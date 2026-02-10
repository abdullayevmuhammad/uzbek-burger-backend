from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, get_object_or_404

from core.models import Branch
from menu.models import Food, FoodType

from .models import LandingSettings, Post


def _common_context(active_page: str):
    settings = LandingSettings.objects.first()
    return {"settings": settings, "active_page": active_page}


def home(request):
    ctx = _common_context("home")

    # Oxirgi yangiliklar
    ctx["posts"] = (
        Post.objects.filter(is_published=True)
        .order_by("-published_at", "-created_at")[:3]
    )

    # Menudan preview (ko'p bo'lsa ham faqat bir nechta ko'rsatamiz)
    foods_qs = (
        Food.objects.filter(is_active=True)
        .select_related("category", "branch")
        .order_by("type", "sort_order", "name")
    )
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

    foods = (
        Food.objects.filter(is_active=True)
        .select_related("category", "branch")
        .order_by("type", "sort_order", "name")
    )

    # Search
    if q:
        foods = foods.filter(
            Q(name__icontains=q)
            | Q(category__name__icontains=q)
        )

    # Type filter
    valid_types = {c[0] for c in FoodType.choices}
    if type_param in valid_types:
        foods = foods.filter(type=type_param)

    ctx["foods"] = foods
    ctx["q"] = q
    ctx["type"] = type_param
    ctx["food_types"] = FoodType.choices

    return render(request, "landing/menu.html", ctx)


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
