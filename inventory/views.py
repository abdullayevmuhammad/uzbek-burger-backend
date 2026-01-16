from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from catalog.models import Product
from .forms import StockImportCreateForm, StockImportItemForm, ProductCreateForm
from .models import BranchProduct, StockImport, StockImportItem
from .services import post_stock_import

from django.contrib import messages

ACTIVE_BRANCH_SESSION_KEY = "active_branch_id"


def _branch_or_forbidden(request):
    b = getattr(request, "active_branch", None)
    if not b:
        raise PermissionError("Faol filial tanlanmagan.")
    return b


def _ordering(request, allowed: dict, default_key: str):
    """
    allowed: {"name": "product__name", "qty": "stock_qty", ...}
    query: ?o=name yoki ?o=-qty
    """
    o = (request.GET.get("o") or default_key).strip()
    desc = o.startswith("-")
    key = o[1:] if desc else o
    field = allowed.get(key, allowed[default_key])
    orm = f"-{field}" if desc else field
    return orm, o  # (django ordering field, current "o")


@login_required
def warehouse_home(request):
    return redirect("stock_list")


# ===== TAB 1: Mahsulotlar / Qoldiq =====
@login_required
def stock_list(request):
    branch = _branch_or_forbidden(request)

    q = (request.GET.get("q") or "").strip()
    ct = (request.GET.get("ct") or "").strip()          # count_type filter
    min_qty = (request.GET.get("min_qty") or "").strip()
    max_qty = (request.GET.get("max_qty") or "").strip()

    allowed = {
        "name": "product__name",
        "qty": "stock_qty",
        "avg": "avg_unit_cost",
        "last": "last_unit_cost",
    }
    ordering, current_o = _ordering(request, allowed, "name")

    qs = BranchProduct.objects.filter(branch=branch).select_related("product")
    qs = qs.filter(product__is_active=True)

    if q:
        qs = qs.filter(
            Q(product__name__icontains=q) |
            Q(product__sku__icontains=q) |
            Q(product__barcode__icontains=q)
        )
    if ct:
        qs = qs.filter(product__count_type=ct)

    # qty filter
    try:
        if min_qty:
            qs = qs.filter(stock_qty__gte=Decimal(min_qty))
        if max_qty:
            qs = qs.filter(stock_qty__lte=Decimal(max_qty))
    except Exception:
        pass

    qs = qs.order_by(ordering, "product__name")

    return render(request, "inventory/stock_list.html", {
        "tab": "products",
        "items": qs,
        "q": q,
        "ct": ct,
        "min_qty": min_qty,
        "max_qty": max_qty,
        "current_o": current_o,
    })


@login_required
@require_http_methods(["GET", "POST"])
def product_create(request):
    branch = _branch_or_forbidden(request)

    if request.method == "POST":
        form = ProductCreateForm(request.POST)
        if form.is_valid():
            p = form.save()
            # shu filialda BranchProduct yo‘q bo‘lsa, 0 bilan yaratib qo‘yamiz
            BranchProduct.objects.get_or_create(branch=branch, product=p)
            return redirect("product_detail", pk=p.id)
    else:
        form = ProductCreateForm()

    return render(request, "inventory/product_create.html", {
        "tab": "products",
        "form": form,
    })


@login_required
def product_detail(request, pk):
    branch = _branch_or_forbidden(request)

    # Product UUID
    product = get_object_or_404(Product, pk=pk)

    bp, _ = BranchProduct.objects.get_or_create(branch=branch, product=product)

    # import tarixini shu product + shu branch bo‘yicha ko‘rsatamiz
    items = (
        StockImportItem.objects
        .filter(product=product, stock_import__branch=branch)
        .select_related("stock_import")
        .order_by("-stock_import__created_at")
    )

    total_qty = items.aggregate(s=Sum("qty"))["s"] or Decimal("0")
    total_cost = items.aggregate(s=Sum("line_total_cost"))["s"] or 0

    rows = []
    for it in items[:300]:
        qty = it.qty
        if qty and qty > 0:
            unit = (Decimal(it.line_total_cost) / qty).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            unit = int(unit)
        else:
            unit = 0
        rows.append({
            "import": it.stock_import,
            "qty": it.qty,
            "line_total_cost": it.line_total_cost,
            "unit_cost": unit,
        })

    return render(request, "inventory/product_detail.html", {
        "tab": "products",
        "product": product,
        "bp": bp,
        "import_rows": rows,
        "total_import_qty": total_qty,
        "total_import_cost": total_cost,
    })


# ===== TAB 2: Importlar =====
@login_required
def import_list(request):
    branch = _branch_or_forbidden(request)

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()

    allowed = {
        "time": "created_at",
        "status": "status",
        "note": "note",
        "sum": "total_cost",
    }
    # annotate uchun ordering keylar bilan ishlaymiz
    o = (request.GET.get("o") or "-time").strip()
    desc = o.startswith("-")
    key = o[1:] if desc else o
    order_key = allowed.get(key, allowed["time"])

    qs = (
        StockImport.objects
        .filter(branch=branch)
        .annotate(total_cost=Sum("items__line_total_cost"))
    )

    if q:
        qs = qs.filter(Q(note__icontains=q))
    if status in {StockImport.Status.DRAFT, StockImport.Status.POSTED}:
        qs = qs.filter(status=status)

    # ordering (annotate fieldlar ham bor)
    orm_order = f"-{order_key}" if desc else order_key
    qs = qs.order_by(orm_order, "-created_at")

    return render(request, "inventory/import_list.html", {
        "tab": "imports",
        "imports": qs,
        "q": q,
        "status": status,
        "current_o": o,
    })


@login_required
@require_http_methods(["GET", "POST"])
def import_create(request):
    branch = _branch_or_forbidden(request)

    if request.method == "POST":
        form = StockImportCreateForm(request.POST, branch=branch)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.branch = branch
            obj.created_by = request.user
            obj.save()
            return redirect("import_detail", pk=obj.pk)
    else:
        form = StockImportCreateForm(branch=branch)

    return render(request, "inventory/import_create.html", {"tab": "imports", "form": form})


@login_required
def import_detail(request, pk):
    branch = _branch_or_forbidden(request)
    obj = get_object_or_404(StockImport, pk=pk, branch=branch)

    items = StockImportItem.objects.filter(stock_import=obj).select_related("product").order_by("product__name")
    total_cost = items.aggregate(s=Sum("line_total_cost"))["s"] or 0

    item_form = StockImportItemForm()
    return render(request, "inventory/import_detail.html", {
        "tab": "imports",
        "imp": obj,
        "items": items,
        "total_cost": total_cost,
        "item_form": item_form,
    })


@login_required
@require_POST
def import_add_item(request, pk):
    branch = _branch_or_forbidden(request)
    imp = get_object_or_404(StockImport, pk=pk, branch=branch)

    if imp.status != StockImport.Status.DRAFT:
        return HttpResponseForbidden("POST qilingan importga mahsulot qo‘shib bo‘lmaydi.")

    form = StockImportItemForm(request.POST)
    if not form.is_valid():
        items = StockImportItem.objects.filter(stock_import=imp).select_related("product").order_by("product__name")
        total_cost = items.aggregate(s=Sum("line_total_cost"))["s"] or 0
        return render(request, "inventory/import_detail.html", {
            "tab": "imports",
            "imp": imp, "items": items, "total_cost": total_cost, "item_form": form
        })

    product = form.cleaned_data["product"]
    qty = form.cleaned_data["qty"]
    line_total_cost = form.cleaned_data["line_total_cost"]

    with transaction.atomic():
        obj, created = StockImportItem.objects.get_or_create(
            stock_import=imp,
            product=product,
            defaults={"qty": qty, "line_total_cost": line_total_cost},
        )
        if not created:
            obj.qty = qty
            obj.line_total_cost = line_total_cost
            obj.save()

        # BranchProduct bo‘lmasa ham yaratib qo‘yamiz (keyin stock update uchun)
        BranchProduct.objects.get_or_create(branch=branch, product=product)

    return redirect("import_detail", pk=imp.pk)


@login_required
@require_POST
def import_post(request, pk):
    branch = _branch_or_forbidden(request)
    imp = get_object_or_404(StockImport, pk=pk, branch=branch)

    if imp.status == StockImport.Status.POSTED:
        messages.info(request, "Bu import allaqachon POST qilingan.")
        return redirect("import_detail", pk=imp.pk)

    if not StockImportItem.objects.filter(stock_import=imp).exists():
        messages.warning(request, "Import itemlari yo‘q. Avval mahsulot qo‘shing.")
        return redirect("import_detail", pk=imp.pk)

    try:
        with transaction.atomic():
            post_stock_import(imp, by_user=request.user)
        messages.success(request, "Import muvaffaqiyatli POST qilindi.")
    except ValueError as e:
        messages.error(request, str(e))
    except Exception:
        messages.error(request, "Kutilmagan xatolik. Qaytadan urinib ko‘ring.")

    return redirect("import_detail", pk=imp.pk)