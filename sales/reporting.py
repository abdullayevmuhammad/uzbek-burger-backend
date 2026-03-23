from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, ExpressionWrapper, F, IntegerField, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from finance.models import CashTransaction, TxnType
from inventory.models import BranchProduct
from sales.models import Order, OrderItem, OrderPayment


LOW_STOCK_THRESHOLDS = {
    "pcs": Decimal("10"),
    "kg": Decimal("2"),
    "l": Decimal("2"),
    "gr": Decimal("1000"),
    "ml": Decimal("1000"),
}


def resolve_reporting_period(range_key: str, date_from_raw: str = "", date_to_raw: str = ""):
    today = timezone.localdate()
    normalized = (range_key or "month").strip().lower()

    if normalized == "day":
        date_from = today
        date_to = today
    elif normalized == "week":
        date_from = today - timedelta(days=today.weekday())
        date_to = today
    elif normalized == "year":
        date_from = today.replace(month=1, day=1)
        date_to = today
    elif normalized == "custom":
        try:
            date_from = datetime.strptime(date_from_raw, "%Y-%m-%d").date()
            date_to = datetime.strptime(date_to_raw, "%Y-%m-%d").date()
        except Exception:
            normalized = "month"
            date_from = today.replace(day=1)
            date_to = today
    else:
        normalized = "month"
        date_from = today.replace(day=1)
        date_to = today

    if date_from > date_to:
        date_from, date_to = date_to, date_from

    return {
        "range_key": normalized,
        "date_from": date_from,
        "date_to": date_to,
    }


def resolve_date_bounds(date_from, date_to):
    current_tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(date_from, time.min), current_tz)
    end_dt = timezone.make_aware(datetime.combine(date_to + timedelta(days=1), time.min), current_tz)
    return start_dt, end_dt


def _empty_daily_series(date_from, date_to):
    series = OrderedDict()
    current = date_from
    while current <= date_to:
        series[current] = {
            "label": current.strftime("%d.%m"),
            "revenue": 0,
            "expenses": 0,
            "profit": 0,
            "orders": 0,
        }
        current += timedelta(days=1)
    return series


def _apply_daily_totals(series, queryset, *, date_field: str, key: str, amount_field: str):
    for row in queryset.annotate(day=TruncDate(date_field)).values("day").annotate(total=Sum(amount_field)).order_by("day"):
        day = row["day"]
        if day in series:
            series[day][key] = int(row["total"] or 0)


def _apply_daily_counts(series, queryset, *, date_field: str, key: str):
    for row in queryset.annotate(day=TruncDate(date_field)).values("day").annotate(total=Count("id")).order_by("day"):
        day = row["day"]
        if day in series:
            series[day][key] = int(row["total"] or 0)


def _serialize_ranked_rows(queryset, *, revenue_field="revenue", quantity_field="quantity", limit=8):
    rows = []
    for item in queryset[:limit]:
        rows.append(
            {
                "name": item.get("name") or item.get("food__name") or item.get("food__category__name") or "Nomsiz",
                "quantity": int(item.get(quantity_field) or 0),
                "revenue": int(item.get(revenue_field) or 0),
            }
        )
    return rows


def _collect_low_stock_alerts(branch, *, limit=10):
    alerts = []
    branch_products = (
        BranchProduct.objects.filter(branch=branch)
        .select_related("product")
        .order_by("stock_qty", "product__name")
    )

    for branch_product in branch_products:
        threshold = LOW_STOCK_THRESHOLDS.get(branch_product.product.count_type)
        if threshold is None:
            continue

        stock_qty = Decimal(branch_product.stock_qty or 0)
        if stock_qty > threshold:
            continue

        alerts.append(
            {
                "product_name": branch_product.product.name,
                "stock_qty": branch_product.stock_qty,
                "unit": branch_product.product.get_count_type_display(),
                "threshold": threshold,
            }
        )

        if len(alerts) >= limit:
            break

    return alerts


def build_branch_analytics(branch, *, date_from, date_to):
    start_dt, end_dt = resolve_date_bounds(date_from, date_to)

    order_window = Order.objects.filter(branch=branch, created_at__gte=start_dt, created_at__lt=end_dt).exclude(status=Order.Status.CANCELED)
    delivered_window = Order.objects.filter(
        branch=branch,
        is_delivered=True,
        delivered_at__gte=start_dt,
        delivered_at__lt=end_dt,
    ).exclude(status=Order.Status.CANCELED)
    payment_window = OrderPayment.objects.filter(order__branch=branch, created_at__gte=start_dt, created_at__lt=end_dt)
    expense_window = CashTransaction.objects.filter(
        branch=branch,
        txn_type=TxnType.EXPENSE,
        occurred_at__gte=start_dt,
        occurred_at__lt=end_dt,
    )
    pending_action_window = (
        Order.objects.filter(branch=branch, total_amount__gt=0, is_locked=False)
        .exclude(status=Order.Status.CANCELED)
        .filter(Q(is_delivered=False) | Q(paid_amount__lt=F("total_amount")))
    )

    revenue_total = int(payment_window.aggregate(total=Sum("amount"))["total"] or 0)
    expenses_total = int(expense_window.aggregate(total=Sum("amount"))["total"] or 0)
    cogs_total = int(delivered_window.aggregate(total=Sum("cogs_amount"))["total"] or 0)
    gross_profit_total = int(delivered_window.aggregate(total=Sum("profit_amount"))["total"] or 0)
    cashflow_total = revenue_total - expenses_total
    order_count = order_window.count()
    delivered_order_count = delivered_window.count()
    paid_order_count = payment_window.values("order_id").distinct().count()
    average_ticket = int(revenue_total / paid_order_count) if paid_order_count else 0
    pending_action_count = pending_action_window.count()
    due_expression = ExpressionWrapper(F("total_amount") - F("paid_amount"), output_field=IntegerField())
    outstanding_balance_total = int(pending_action_window.aggregate(total=Sum(due_expression))["total"] or 0)

    item_window = OrderItem.objects.filter(
        order__branch=branch,
        order__is_delivered=True,
        order__delivered_at__gte=start_dt,
        order__delivered_at__lt=end_dt,
    ).exclude(order__status=Order.Status.CANCELED)

    top_products_qty = _serialize_ranked_rows(
        item_window.values("food__name")
        .annotate(quantity=Sum("qty"), revenue=Sum("line_total"))
        .order_by("-quantity", "-revenue"),
        limit=10,
    )
    top_products_revenue = _serialize_ranked_rows(
        item_window.values("food__name")
        .annotate(quantity=Sum("qty"), revenue=Sum("line_total"))
        .order_by("-revenue", "-quantity"),
        limit=10,
    )

    best_by_type = {}
    for food_type in ["FASTFOOD", "DRINK", "SET"]:
        best_by_type[food_type] = _serialize_ranked_rows(
            item_window.filter(food__type=food_type)
            .values("food__name")
            .annotate(quantity=Sum("qty"), revenue=Sum("line_total"))
            .order_by("-quantity", "-revenue"),
            limit=5,
        )

    category_sales = _serialize_ranked_rows(
        item_window.values("food__category__name")
        .annotate(quantity=Sum("qty"), revenue=Sum("line_total"))
        .order_by("-revenue", "-quantity"),
        limit=10,
    )

    series = _empty_daily_series(date_from, date_to)
    _apply_daily_totals(series, payment_window, date_field="created_at", key="revenue", amount_field="amount")
    _apply_daily_totals(series, expense_window, date_field="occurred_at", key="expenses", amount_field="amount")
    _apply_daily_totals(series, delivered_window, date_field="delivered_at", key="profit", amount_field="profit_amount")
    _apply_daily_counts(series, order_window, date_field="created_at", key="orders")

    low_stock_alerts = _collect_low_stock_alerts(branch)
    has_activity = any(
        [
            revenue_total,
            expenses_total,
            gross_profit_total,
            order_count,
            delivered_order_count,
            paid_order_count,
        ]
    )

    period_rows = list(series.values())

    return {
        "date_from": date_from,
        "date_to": date_to,
        "has_activity": has_activity,
        "kpis": {
            "revenue_total": revenue_total,
            "expenses_total": expenses_total,
            "gross_profit_total": gross_profit_total,
            "cashflow_total": cashflow_total,
            "cogs_total": cogs_total,
            "order_count": order_count,
            "delivered_order_count": delivered_order_count,
            "paid_order_count": paid_order_count,
            "average_ticket": average_ticket,
            "pending_action_count": pending_action_count,
            "outstanding_balance_total": outstanding_balance_total,
            "low_stock_count": len(low_stock_alerts),
        },
        "notes": {
            "gross_profit": "Brutto foyda topshirilgan buyurtmalarning sotuv summasi minus hisoblangan tannarxi asosida ko'rsatildi.",
            "cashflow": "Kassa oqimi tushgan to'lovlar minus expense tranzaksiyalari bo'yicha hisoblandi.",
        },
        "period_rows": period_rows,
        "top_products_qty": top_products_qty,
        "top_products_revenue": top_products_revenue,
        "best_fastfood": best_by_type["FASTFOOD"],
        "best_drinks": best_by_type["DRINK"],
        "best_sets": best_by_type["SET"],
        "category_sales": category_sales,
        "low_stock_alerts": low_stock_alerts,
    }
