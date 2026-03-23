from __future__ import annotations

import json
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, ExpressionWrapper, F, IntegerField, Sum, Value, When
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods, require_POST

from core.middleware import get_active_branch
from core.services import ensure_branch_is_operational
from finance.models import MoneyAccount
from finance.utils import parse_uzs_amount
from menu.models import Food, FoodType
from users.utils import is_admin_user

from .models import Order
from .reporting import build_branch_analytics, resolve_date_bounds, resolve_reporting_period
from .services import (
    OrderValidationError,
    build_receipt_context,
    cancel_order,
    count_pending_action_orders,
    create_order_with_items,
    ensure_kitchen_task,
    get_pending_action_orders,
    mark_delivered,
    pay_order,
)


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200
PAGE_SIZE_CHOICES = [20, 50, 100, 200]


def _is_admin_like(user) -> bool:
    return is_admin_user(user)


def _require_branch(request):
    """POS ishlashi uchun faol filial kerak."""
    branch = get_active_branch(request)
    if branch:
        return ensure_branch_is_operational(branch)
    if _is_admin_like(request.user):
        raise LookupError("branch_not_selected")
    raise PermissionError("Faol filial tanlanmagan")


def _branch_accounts(branch, *, ensure_default: bool = False):
    """Filial kassalari (MoneyAccount)."""
    qs = MoneyAccount.objects.filter(branch=branch, is_active=True).order_by("name")
    if ensure_default and not qs.exists():
        from finance.models import AccountKind

        MoneyAccount.objects.get_or_create(
            branch=branch,
            name="Kassa",
            defaults={"kind": AccountKind.CASH, "is_active": True},
        )
        qs = MoneyAccount.objects.filter(branch=branch, is_active=True).order_by("name")
    return qs


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _json_error(message: str, *, status: int = 400):
    return JsonResponse({"ok": False, "message": message}, status=status)


def _parse_page_size(raw_value: str):
    value = (raw_value or "").strip().lower()
    if value == "all":
        return "all"

    try:
        parsed = int(value or DEFAULT_PAGE_SIZE)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE

    return max(1, min(parsed, MAX_PAGE_SIZE))


def _update_querystring(querydict, **updates):
    params = querydict.copy()
    for key, value in updates.items():
        if value in (None, ""):
            params.pop(key, None)
            continue
        params[key] = value
    return params.urlencode()


def _quick_action_accounts_payload(branch):
    return [
        {
            "id": str(account.id),
            "name": account.name,
        }
        for account in _branch_accounts(branch)
    ]


def _order_due(order):
    return max(0, int(order.total_amount) - int(order.paid_amount))


def _render_order_status_html(request, order):
    return render_to_string(
        "sales/partials/order_status_badges.html",
        {
            "o": order,
            "due": _order_due(order),
        },
        request=request,
    )


def _render_pending_tasks_html(request, branch):
    pending_orders = get_pending_action_orders(branch)
    pending_task_count = count_pending_action_orders(branch)
    html = render_to_string(
        "sales/partials/pending_task_bar.html",
        {
            "pending_orders": pending_orders,
            "pending_task_count": pending_task_count,
        },
        request=request,
    )
    return html, pending_task_count


def _build_quick_action_response(request, order, message):
    refreshed_order = (
        Order.objects.filter(pk=order.pk)
        .select_related("created_by", "paid_by", "delivered_by", "branch", "kitchen_task")
        .prefetch_related("items__food")
        .get()
    )
    status_html = _render_order_status_html(request, refreshed_order)
    pending_tasks_html, pending_task_count = _render_pending_tasks_html(request, refreshed_order.branch)

    return JsonResponse(
        {
            "ok": True,
            "message": message,
            "order_id": str(refreshed_order.pk),
            "due": _order_due(refreshed_order),
            "is_delivered": refreshed_order.is_delivered,
            "is_fully_paid": refreshed_order.is_fully_paid,
            "task_relevant": (not refreshed_order.is_delivered) or (not refreshed_order.is_fully_paid),
            "status_html": status_html,
            "pending_tasks_html": pending_tasks_html,
            "pending_task_count": pending_task_count,
        }
    )


@login_required
def pos_orders(request):
    try:
        branch = _require_branch(request)
    except LookupError:
        return redirect("select_branch")
    except PermissionError:
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    status = (request.GET.get("status") or "").strip()
    delivered = (request.GET.get("delivered") or "").strip()
    payment = (request.GET.get("payment") or "").strip()
    period = resolve_reporting_period(request.GET.get("period"))
    page_size = _parse_page_size(request.GET.get("page_size"))
    start_dt, end_dt = resolve_date_bounds(period["date_from"], period["date_to"])

    qs = (
        Order.objects.filter(branch=branch)
        .select_related("created_by", "paid_by", "delivered_by")
        .filter(created_at__gte=start_dt, created_at__lt=end_dt)
        .order_by("-created_at")
    )

    if status in {Order.Status.DRAFT, Order.Status.PAID, Order.Status.CANCELED}:
        qs = qs.filter(status=status)

    if delivered in {"0", "1"}:
        qs = qs.filter(is_delivered=(delivered == "1"))

    if payment == "paid":
        qs = qs.filter(total_amount__gt=0, paid_amount__gte=F("total_amount"))
    elif payment == "partial":
        qs = qs.filter(paid_amount__gt=0, paid_amount__lt=F("total_amount"))
    elif payment == "unpaid":
        qs = qs.filter(paid_amount=0)

    due_expression = ExpressionWrapper(F("total_amount") - F("paid_amount"), output_field=IntegerField())
    summary_row = qs.aggregate(
        order_count=Count("pk"),
        total_amount_sum=Sum("total_amount"),
        paid_amount_sum=Sum("paid_amount"),
        outstanding_amount_sum=Sum(due_expression),
    )
    order_summary = {
        "count": int(summary_row["order_count"] or 0),
        "total_amount": int(summary_row["total_amount_sum"] or 0),
        "paid_amount": int(summary_row["paid_amount_sum"] or 0),
        "outstanding_amount": int(summary_row["outstanding_amount_sum"] or 0),
    }

    page_obj = None
    page_numbers = []
    if page_size == "all":
        orders = list(qs)
    else:
        paginator = Paginator(qs, page_size)
        page_obj = paginator.get_page(request.GET.get("page"))
        ellipsis = getattr(paginator, "ELLIPSIS", "…")
        page_numbers = [
            "..." if item == ellipsis else item
            for item in paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1)
        ]
        orders = list(page_obj.object_list)

    accounts = list(_branch_accounts(branch))
    pagination_query = _update_querystring(request.GET, page=None)
    clear_filters_url = f"{request.path}?period={period['range_key']}"
    return render(
        request,
        "sales/pos_orders.html",
        {
            "branch": branch,
            "orders": orders,
            "status": status,
            "delivered": delivered,
            "payment": payment,
            "period_key": period["range_key"],
            "period_date_from": period["date_from"],
            "period_date_to": period["date_to"],
            "order_summary": order_summary,
            "page_obj": page_obj,
            "page_numbers": page_numbers,
            "is_paginated": bool(page_obj and page_obj.paginator.num_pages > 1),
            "page_size": str(page_size),
            "page_size_choices": PAGE_SIZE_CHOICES,
            "pagination_query": pagination_query,
            "clear_filters_url": clear_filters_url,
            "Status": Order.Status,
            "quick_action_accounts_json": json.dumps(
                [{"id": str(account.id), "name": account.name} for account in accounts],
                ensure_ascii=False,
            ),
        },
    )


@login_required
def pos_analytics(request):
    try:
        branch = _require_branch(request)
    except LookupError:
        return redirect("select_branch")
    except PermissionError:
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    period = resolve_reporting_period(
        request.GET.get("range"),
        request.GET.get("date_from"),
        request.GET.get("date_to"),
    )
    analytics = build_branch_analytics(
        branch,
        date_from=period["date_from"],
        date_to=period["date_to"],
    )

    return render(
        request,
        "sales/pos_analytics.html",
        {
            "branch": branch,
            "range_key": period["range_key"],
            "date_from": period["date_from"].isoformat(),
            "date_to": period["date_to"].isoformat(),
            "analytics": analytics,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def pos_order_create(request):
    try:
        branch = _require_branch(request)
    except LookupError:
        return redirect("select_branch")
    except PermissionError:
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    foods_qs = (
        Food.objects.filter(is_active=True, branch=branch)
        .select_related("category")
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
    single_account = accounts[0] if len(accounts) == 1 else None
    pending_orders = get_pending_action_orders(branch)
    pending_task_count = count_pending_action_orders(branch)

    if request.method == "POST":
        raw_items = request.POST.get("items_json") or "[]"
        try:
            items = json.loads(raw_items)
        except Exception:
            messages.error(request, "Chek ma'lumotlari xato (items_json).")
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
                order = create_order_with_items(
                    branch=branch,
                    created_by=request.user,
                    order_type=order_type,
                    note=note,
                    items=items,
                )

                order.refresh_from_db()

                if is_delivered:
                    mark_delivered(order, by_user=request.user)

                if is_paid:
                    if not account_id and len(accounts) > 1:
                        raise ValueError("To'lov hisobini tanlang.")

                    if not account_id:
                        acc = single_account
                    else:
                        acc = get_object_or_404(MoneyAccount, id=account_id, branch=branch, is_active=True)

                    if acc is None:
                        raise ValueError("Faol to'lov hisobi topilmadi. Admin: filial uchun kamida bitta hisob yarating.")

                    if paid_amount_raw:
                        amount = parse_uzs_amount(paid_amount_raw)
                    else:
                        amount = int(order.total_amount)

                    if amount > 0:
                        pay_order(order, account=acc, amount=amount, by_user=request.user)

                return redirect("sales:pos_order_detail", pk=order.pk)

        except OrderValidationError as e:
            messages.error(request, str(e))
            return redirect("sales:pos_order_create")
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
            "single_account": single_account,
            "has_payment_accounts": bool(accounts),
            "OrderType": Order.OrderType,
            "pending_orders": pending_orders,
            "pending_task_count": pending_task_count,
            "quick_action_accounts_json": json.dumps(_quick_action_accounts_payload(branch), ensure_ascii=False),
            "hide_sidebar": True,
            "hide_topbar": True,
            "body_class": "no-sidebar pos-no-nav",
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
    single_account = accounts[0] if len(accounts) == 1 else None
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
            "single_account": single_account,
            "has_payment_accounts": bool(accounts),
            "due": due,
            "Status": Order.Status,
            "OrderType": Order.OrderType,
        },
    )


@login_required
@require_POST
def pos_order_pay(request, pk):
    ajax_request = _is_ajax(request)
    try:
        branch = _require_branch(request)
    except LookupError:
        return _json_error("Filial tanlanmagan.", status=400) if ajax_request else redirect("select_branch")
    except PermissionError:
        if ajax_request:
            return _json_error("Faol filial tanlanmagan.", status=403)
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    order = get_object_or_404(Order, pk=pk, branch=branch)

    if order.is_locked:
        if ajax_request:
            return _json_error("Bu buyurtma yakunlangan. Endi o'zgartirib bo'lmaydi.")
        messages.error(request, "Bu buyurtma yakunlangan. Endi o'zgartirib bo'lmaydi.")
        return redirect("sales:pos_order_detail", pk=pk)

    account_id = (request.POST.get("account_id") or "").strip()
    amount_raw = (request.POST.get("amount") or "").strip()
    note = (request.POST.get("note") or "").strip() or None

    accounts = list(_branch_accounts(branch))
    single_account = accounts[0] if len(accounts) == 1 else None

    if not account_id:
        if single_account is not None:
            acc = single_account
        else:
            message = "Faol to'lov hisobi topilmadi. Admin: filial uchun kamida bitta hisob yarating."
            if accounts:
                message = "Kassa tanlang."
            if ajax_request:
                return _json_error(message)
            messages.error(request, message)
            return redirect("sales:pos_order_detail", pk=pk)
    else:
        acc = get_object_or_404(MoneyAccount, id=account_id, branch=branch, is_active=True)

    try:
        if amount_raw:
            amount = parse_uzs_amount(amount_raw)
        else:
            amount = _order_due(order)
    except Exception:
        if ajax_request:
            return _json_error("To'lov summasi noto'g'ri.")
        messages.error(request, "To'lov summasi noto'g'ri.")
        return redirect("sales:pos_order_detail", pk=pk)

    try:
        pay_order(order, account=acc, amount=amount, note=note, by_user=request.user)
        if ajax_request:
            return _build_quick_action_response(request, order, "To'lov qabul qilindi.")
        messages.success(request, "To'lov qabul qilindi.")
    except Exception as e:
        if ajax_request:
            return _json_error(f"To'lovda xatolik: {e}")
        messages.error(request, f"To'lovda xatolik: {e}")

    return redirect("sales:pos_order_detail", pk=pk)


@login_required
@require_POST
def pos_order_deliver(request, pk):
    ajax_request = _is_ajax(request)
    try:
        branch = _require_branch(request)
    except LookupError:
        return _json_error("Filial tanlanmagan.", status=400) if ajax_request else redirect("select_branch")
    except PermissionError:
        if ajax_request:
            return _json_error("Faol filial tanlanmagan.", status=403)
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    order = get_object_or_404(Order, pk=pk, branch=branch)

    if order.is_locked:
        if ajax_request:
            return _json_error("Bu buyurtma yakunlangan. Endi o'zgartirib bo'lmaydi.")
        messages.error(request, "Bu buyurtma yakunlangan. Endi o'zgartirib bo'lmaydi.")
        return redirect("sales:pos_order_detail", pk=pk)

    try:
        mark_delivered(order, by_user=request.user)
        if ajax_request:
            return _build_quick_action_response(request, order, "Buyurtma topshirildi deb belgilandi.")
        messages.success(request, "Order 'topshirildi' deb belgilandi (stock yechildi).")
    except Exception as e:
        if ajax_request:
            return _json_error(f"Topshirishda xatolik: {e}")
        messages.error(request, f"Topshirishda xatolik: {e}")

    return redirect("sales:pos_order_detail", pk=pk)


@login_required
def pos_pending_tasks_feed(request):
    try:
        branch = _require_branch(request)
    except LookupError:
        return _json_error("Filial tanlanmagan.", status=400)
    except PermissionError:
        return _json_error("Faol filial tanlanmagan.", status=403)

    html, count = _render_pending_tasks_html(request, branch)
    return JsonResponse({"ok": True, "html": html, "count": count})


@login_required
@require_POST
def pos_order_cancel(request, pk):
    try:
        branch = _require_branch(request)
    except LookupError:
        return redirect("select_branch")
    except PermissionError:
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    order = get_object_or_404(Order, pk=pk, branch=branch)

    try:
        cancel_order(order, by_user=request.user)
        messages.success(request, "Buyurtma bekor qilindi.")
    except Exception as e:
        messages.error(request, f"Bekor qilishda xatolik: {e}")

    return redirect("sales:pos_order_detail", pk=pk)


@login_required
def pos_menu_json(request):
    try:
        branch = _require_branch(request)
    except LookupError:
        return JsonResponse({"error": "branch_not_selected"}, status=400)
    except PermissionError:
        return JsonResponse({"error": "no_branch"}, status=403)

    foods_qs = (
        Food.objects.filter(is_active=True, branch=branch)
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


@login_required
def pos_order_receipt(request, pk):
    try:
        branch = _require_branch(request)
    except LookupError:
        return redirect("select_branch")
    except PermissionError:
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    order = get_object_or_404(Order, pk=pk, branch=branch)
    paper_width = (request.GET.get("paper") or "58").strip()
    if paper_width not in {"58", "80"}:
        paper_width = "58"
    ctx = build_receipt_context(order)
    ctx.update({"branch": branch, "paper_width": paper_width})
    return render(request, "sales/receipt.html", ctx)


@login_required
def pos_order_kitchen_task(request, pk):
    try:
        branch = _require_branch(request)
    except LookupError:
        return redirect("select_branch")
    except PermissionError:
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    order = get_object_or_404(Order.objects.select_related("branch"), pk=pk, branch=branch)
    task = ensure_kitchen_task(order, actor=request.user)

    if request.method == "POST":
        new_status = request.POST.get("status")
        if new_status in {c for c, _ in task.Status.choices}:
            task.status = new_status
            task.updated_by = request.user
            task.save(update_fields=["status", "updated_by", "updated_at"])
        return redirect("sales:pos_order_kitchen", pk=pk)

    return render(
        request,
        "sales/kitchen_task.html",
        {
            "branch": branch,
            "order": order,
            "task": task,
            "items": order.items.select_related("food"),
            "hide_sidebar": True,
            "hide_topbar": True,
            "body_class": "no-sidebar pos-no-nav",
        },
    )
@login_required
def pos_order_receipt_data(request, pk):
    try:
        branch = _require_branch(request)
    except LookupError:
        return redirect("select_branch")
    except PermissionError:
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    order = get_object_or_404(Order, pk=pk, branch=branch)
    ctx = build_receipt_context(order)

    return JsonResponse({
        "ok": True,
        "doc_type": "receipt",
        "branch": {
            "name": ctx["branch"].name,
            "address": getattr(ctx["branch"], "public_address", "") or "",
            "phone": getattr(ctx["branch"], "public_phone", "") or "",
        },
        "order": {
            "id": str(ctx["order"].id)[:8],
            "created_at": ctx["order"].created_at.strftime("%d.%m.%Y %H:%M"),
            "cashier": ctx["order"].created_by.username if ctx["order"].created_by else "-",
            "type": ctx["order"].get_order_type_display(),
            "total_amount": ctx["total_amount"],
            "paid_amount": ctx["paid_amount"],
            "due": ctx["due"],
            "is_delivered": bool(ctx["order"].is_delivered),
            "is_fully_paid": bool(ctx["order"].is_fully_paid),
        },
        "items": ctx["items"],
        "payments": [
            {
                "amount": p["amount"],
                "account": p["account"],
                "created_at": p["created_at"].strftime("%d.%m %H:%M"),
            }
            for p in ctx["payments"]
        ],
    })

@login_required
def pos_order_kitchen_print_data(request, pk):
    try:
        branch = _require_branch(request)
    except LookupError:
        return redirect("select_branch")
    except PermissionError:
        return HttpResponseForbidden("Sizga filial biriktirilmagan yoki faol filial tanlanmagan.")

    order = get_object_or_404(Order.objects.select_related("branch"), pk=pk, branch=branch)
    task = ensure_kitchen_task(order, actor=request.user)

    return JsonResponse({
        "ok": True,
        "doc_type": "kitchen",
        "branch": {
            "name": branch.name,
        },
        "order": {
            "id": str(order.id)[:8],
            "created_at": order.created_at.strftime("%d.%m.%Y %H:%M"),
            "type": order.get_order_type_display(),
        },
        "items": [
            {
                "name": it.food.name,
                "qty": it.qty,
            }
            for it in order.items.select_related("food").all()
        ],
        "note": task.note or order.note or "",
    })
