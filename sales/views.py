from __future__ import annotations

import json
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core.middleware import get_active_branch
from finance.models import AccountKind, MoneyAccount
from menu.models import Food, FoodType
from users.models import StaffRole

from .models import Order, OrderItem
from .services import mark_delivered, pay_order, recalc_order_totals


def _is_admin_like(user) -> bool:
    if user.is_superuser:
        return True
    prof = getattr(user, "profile", None) or getattr(user, "staffprofile", None)
    role = getattr(prof, "role", None) if prof else None
    return role == StaffRole.OWNER


def _require_branch(request):
    """POS ishlashi uchun faol filial kerak."""
    branch = get_active_branch(request)
    if branch:
        return branch
    if _is_admin_like(request.user):
        # owner -> filial tanlashga yuboramiz
        raise LookupError("branch_not_selected")
    raise PermissionError("Faol filial tanlanmagan")


def _branch_accounts(branch):
    """Filial kassalari (MoneyAccount)."""
    qs = MoneyAccount.objects.filter(branch=branch, is_active=True).order_by("name")
    # Hech bo'lmasa bitta kassa bo'lsin (signal ishlamagan bo'lsa ham)
    if not qs.exists():
        MoneyAccount.objects.get_or_create(
            branch=branch,
            name="Kassa",
            defaults={"kind": AccountKind.CASH, "is_active": True},
        )
        qs = MoneyAccount.objects.filter(branch=branch, is_active=True).order_by("name")
    return qs


@login_required
def pos_orders(request):
    """Operator uchun: filial orderlari ro'yxati."""
    try:
        branch = _require_branch(request)
    except LookupError:
        return redirect("select_branch")
    except PermissionError:
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    status = (request.GET.get("status") or "").strip()
    delivered = (request.GET.get("delivered") or "").strip()  # '1' / '0'

    qs = (
        Order.objects.filter(branch=branch)
        .select_related("created_by", "paid_by", "delivered_by")
        .order_by("-created_at")
    )

    if status in {Order.Status.DRAFT, Order.Status.PAID, Order.Status.CANCELED}:
        qs = qs.filter(status=status)

    if delivered in {"0", "1"}:
        qs = qs.filter(is_delivered=(delivered == "1"))

    orders = list(qs[:200])

    return render(
        request,
        "sales/pos_orders.html",
        {
            "branch": branch,
            "orders": orders,
            "status": status,
            "delivered": delivered,
            "Status": Order.Status,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def pos_order_create(request):
    """Yangi order yaratish (menu + chek)."""
    try:
        branch = _require_branch(request)
    except LookupError:
        return redirect("select_branch")
    except PermissionError:
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    foods_qs = (
        Food.objects.filter(is_active=True, branch=branch)
        .select_related("category")
        .order_by("type", "category__sort_order", "sort_order", "name")
    )

    # JS uchun minimal JSON
    foods_json: list[dict[str, Any]] = []
    for f in foods_qs:
        img = None
        try:
            if f.image:
                img = f.image.url
        except Exception:
            img = None

        foods_json.append(
            {
                "id": str(f.id),
                "name": f.name,
                "type": f.type,
                "sell_price": int(f.sell_price),
                "image": img,
            }
        )

    accounts = list(_branch_accounts(branch))

    if request.method == "POST":
        raw_items = request.POST.get("items_json") or "[]"
        try:
            items = json.loads(raw_items)
            if not isinstance(items, list):
                raise ValueError
        except Exception:
            messages.error(request, "Chek ma'lumotlari xato (items_json).")
            return redirect("sales:pos_order_create")

        if not items:
            messages.error(request, "Kamida bitta taom tanlang.")
            return redirect("sales:pos_order_create")

        order_type = request.POST.get("order_type") or Order.OrderType.DINE_IN
        if order_type not in {c for c, _ in Order.OrderType.choices}:
            order_type = Order.OrderType.DINE_IN

        is_paid = (request.POST.get("is_paid") or "") == "1"
        is_delivered = (request.POST.get("is_delivered") or "") == "1"

        account_id = (request.POST.get("account_id") or "").strip()
        paid_amount_raw = (request.POST.get("paid_amount") or "").strip()

        note = (request.POST.get("note") or "").strip() or None

        try:
            with transaction.atomic():
                order = Order.objects.create(
                    branch=branch,
                    order_type=order_type,
                    note=note,
                    created_by=request.user,
                )

                # items
                for it in items:
                    food_id = (it.get("food") or "").strip()
                    qty = int(it.get("qty") or 0)

                    if not food_id or qty <= 0:
                        continue

                    food = get_object_or_404(Food, id=food_id, branch=branch, is_active=True)

                    OrderItem.objects.create(
                        order=order,
                        food=food,
                        qty=qty,
                        unit_price=int(food.sell_price),
                        line_total=0,  # save() qayta hisoblaydi
                    )

                recalc_order_totals(order)
                order.refresh_from_db()

                # topshirildi -> stock yechish
                if is_delivered:
                    mark_delivered(order, by_user=request.user)

                # to'lov
                if is_paid:
                    if not account_id:
                        # default: birinchi account
                        acc = accounts[0] if accounts else None
                    else:
                        acc = get_object_or_404(MoneyAccount, id=account_id, branch=branch, is_active=True)

                    if acc is None:
                        raise ValueError("Kassa topilmadi. Admin: filialga kassa yarating.")

                    if paid_amount_raw:
                        amount = int(float(paid_amount_raw))
                    else:
                        amount = int(order.total_amount)

                    if amount > 0:
                        pay_order(order, account=acc, amount=amount, by_user=request.user)

                return redirect("sales:pos_order_detail", pk=order.pk)

        except Exception as e:
            messages.error(request, f"Order yaratilmadi: {e}")
            return redirect("sales:pos_order_create")

    return render(
        request,
        "sales/pos_order_create.html",
        {
            "branch": branch,
            "foods": list(foods_qs),
            "foods_json": json.dumps(foods_json, ensure_ascii=False),
            "FoodType": FoodType,
            "accounts": accounts,
            "OrderType": Order.OrderType,
        },
    )


@login_required
def pos_order_detail(request, pk):
    try:
        branch = _require_branch(request)
    except LookupError:
        return redirect("select_branch")
    except PermissionError:
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    order = get_object_or_404(
        Order.objects.select_related("created_by", "paid_by", "delivered_by"),
        pk=pk,
        branch=branch,
    )
    items = list(order.items.select_related("food").all().order_by("food__name"))
    payments = list(order.payments.select_related("account").all().order_by("-created_at"))

    accounts = list(_branch_accounts(branch))

    due = max(0, int(order.total_amount) - int(order.paid_amount))

    return render(
        request,
        "sales/pos_order_detail.html",
        {
            "branch": branch,
            "order": order,
            "items": items,
            "payments": payments,
            "accounts": accounts,
            "due": due,
            "Status": Order.Status,
            "OrderType": Order.OrderType,
        },
    )


@login_required
@require_POST
def pos_order_pay(request, pk):
    try:
        branch = _require_branch(request)
    except LookupError:
        return redirect("select_branch")
    except PermissionError:
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    order = get_object_or_404(Order, pk=pk, branch=branch)

    if order.is_locked:
        messages.error(request, "Bu buyurtma yakunlangan. Endi o'zgartirib bo'lmaydi.")
        return redirect("sales:pos_order_detail", pk=pk)

    account_id = (request.POST.get("account_id") or "").strip()
    amount_raw = (request.POST.get("amount") or "").strip()
    note = (request.POST.get("note") or "").strip() or None

    if not account_id:
        messages.error(request, "Kassa tanlang.")
        return redirect("sales:pos_order_detail", pk=pk)

    try:
        amount = int(float(amount_raw))
    except Exception:
        amount = 0

    acc = get_object_or_404(MoneyAccount, id=account_id, branch=branch, is_active=True)

    try:
        pay_order(order, account=acc, amount=amount, note=note, by_user=request.user)
        messages.success(request, "To'lov qabul qilindi.")
    except Exception as e:
        messages.error(request, f"To'lovda xatolik: {e}")

    return redirect("sales:pos_order_detail", pk=pk)


@login_required
@require_POST
def pos_order_deliver(request, pk):
    try:
        branch = _require_branch(request)
    except LookupError:
        return redirect("select_branch")
    except PermissionError:
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    order = get_object_or_404(Order, pk=pk, branch=branch)

    if order.is_locked:
        messages.error(request, "Bu buyurtma yakunlangan. Endi o'zgartirib bo'lmaydi.")
        return redirect("sales:pos_order_detail", pk=pk)

    try:
        mark_delivered(order, by_user=request.user)
        messages.success(request, "Order 'topshirildi' deb belgilandi (stock yechildi).")
    except Exception as e:
        messages.error(request, f"Topshirishda xatolik: {e}")

    return redirect("sales:pos_order_detail", pk=pk)


@login_required
def pos_menu_json(request):
    """(Ixtiyoriy) Menu JSON — front uchun."""
    try:
        branch = _require_branch(request)
    except LookupError:
        return JsonResponse({"error": "branch_not_selected"}, status=400)
    except PermissionError:
        return JsonResponse({"error": "no_branch"}, status=403)

    foods_qs = Food.objects.filter(is_active=True, branch=branch).order_by("type", "sort_order", "name")

    out = []
    for f in foods_qs:
        out.append(
            {
                "id": str(f.id),
                "name": f.name,
                "type": f.type,
                "sell_price": int(f.sell_price),
            }
        )
    return JsonResponse({"branch": str(branch.id), "foods": out})


"""Note: order finalize alohida view kerak emas.
Order avtomatik yakunlanadi: (1) topshirildi + (2) to'lov to'liq bo'lsa -> is_locked=True.
"""
