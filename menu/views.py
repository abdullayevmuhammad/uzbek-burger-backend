from __future__ import annotations

from collections import OrderedDict

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from core.middleware import get_active_branch
from users.models import StaffRole

from .forms import FoodForm
from .models import Food, FoodType, FoodCategory


def _is_admin_like(user) -> bool:
    if user.is_superuser:
        return True
    prof = getattr(user, "profile", None) or getattr(user, "staffprofile", None)
    role = getattr(prof, "role", None) if prof else None
    return role == StaffRole.OWNER


def _staff_only(user) -> bool:
    return user.is_authenticated and (user.is_staff or user.is_superuser or _is_admin_like(user))


def _type_label(value) -> str:
    try:
        # TextChoices
        return dict(FoodType.choices).get(value, str(value))
    except Exception:
        return str(value)


@login_required
def menu_board(request):
    branch = get_active_branch(request)

    mode = request.GET.get("type")  # FASTFOOD / DRINK / SET
    cat = request.GET.get("cat")

    # default = ALL
    if not mode:
        mode = "ALL"

    qs = Food.objects.all()
    if branch:
        qs = qs.filter(branch=branch)
    qs = qs.filter(is_active=True).select_related("category")

    context = {
        "branch": branch,
        "FoodType": FoodType,
        "mode": mode,
        "active_type": mode,  # backward compat (templates)
        "active_cat": cat,
        "categories": [],
        "foods": [],
        "groups": [],
    }

    if mode == "ALL":
        foods = qs.order_by("type", "category__name", "sort_order", "name")
        grouped: "OrderedDict[tuple[str,str,str], list]" = OrderedDict()
        for f in foods:
            t_lbl = _type_label(getattr(f, "type", "")) or "—"
            c_obj = getattr(f, "category", None)
            c_lbl = getattr(c_obj, "name", None) or "Boshqa"
            c_id = str(getattr(c_obj, "id", "")) if c_obj else ""
            key = (t_lbl, c_lbl, c_id)
            grouped.setdefault(key, []).append(f)
        context["groups"] = list(grouped.items())
        return render(request, "menu/board.html", context)

    # mode = one type
    foods = qs.filter(type=mode)
    if cat:
        foods = foods.filter(category_id=cat)

    # categories list for filter
    try:
        cqs = FoodCategory.objects.all()
        if branch:
            cqs = cqs.filter(branch=branch)
        cqs = cqs.filter(type=mode).order_by("name")
        context["categories"] = list(cqs)
    except Exception:
        context["categories"] = []

    context["foods"] = foods.order_by("sort_order", "name")
    return render(request, "menu/board.html", context)


@login_required
def food_json(request, food_id):
    """Food dialog uchun JSON. Variantlar ishlatilmaydi."""
    branch = get_active_branch(request)
    qs = Food.objects.all()
    if branch:
        qs = qs.filter(branch=branch)

    food = get_object_or_404(qs.select_related("category"), id=food_id)

    image_url = None
    try:
        if food.image:
            image_url = food.image.url
    except Exception:
        image_url = None

    cat_name = None
    try:
        cat_name = food.category.name if food.category else None
    except Exception:
        cat_name = None

    items = []
    try:
        for it in food.items.select_related("product").all():
            items.append({
                "product": getattr(it.product, "name", str(it.product)),
                "qty": str(it.qty),
                "unit": getattr(it.product, "count_type", ""),
            })
    except Exception:
        items = []

    return JsonResponse({
        "id": str(food.id),
        "name": food.name,
        "sell_price": int(getattr(food, "sell_price", 0) or 0),
        "image": image_url,
        "category": cat_name,
        "items": items,
    })


# -------------------------
# CRUD (staff only)
# -------------------------


@user_passes_test(_staff_only)
def food_list(request):
    branch = get_active_branch(request)
    qs = Food.objects.all()
    if branch:
        qs = qs.filter(branch=branch)
    foods = qs.select_related("category").order_by("type", "category__name", "sort_order", "name")
    return render(request, "menu/food_list.html", {"foods": foods})


@user_passes_test(_staff_only)
def food_add(request):
    branch = get_active_branch(request)
    if request.method == "POST":
        form = FoodForm(request.POST, request.FILES)
        if form.is_valid():
            food = form.save(commit=False)
            if branch and hasattr(food, "branch_id"):
                food.branch = branch
            food.save()
            form.save_m2m()
            return redirect("menu_food_edit", food_id=food.id)
    else:
        form = FoodForm()
    return render(request, "menu/food_form.html", {"form": form})


@user_passes_test(_staff_only)
def food_edit(request, food_id):
    branch = get_active_branch(request)
    qs = Food.objects.all()
    if branch:
        qs = qs.filter(branch=branch)
    food = get_object_or_404(qs, id=food_id)

    if request.method == "POST":
        form = FoodForm(request.POST, request.FILES, instance=food)
        if form.is_valid():
            form.save()
            return redirect("menu_food_edit", food_id=food.id)
    else:
        form = FoodForm(instance=food)

    return render(request, "menu/food_edit.html", {
        "food": food,
        "form": form,
    })


@user_passes_test(_staff_only)
def food_delete(request, food_id):
    branch = get_active_branch(request)
    qs = Food.objects.all()
    if branch:
        qs = qs.filter(branch=branch)
    food = get_object_or_404(qs, id=food_id)

    if request.method == "POST":
        food.delete()
        return redirect("menu_food_list")

    return render(request, "menu/food_delete.html", {"food": food})
