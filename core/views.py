from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from core.models import Branch
from users.utils import get_profile, is_admin_user

ACTIVE_BRANCH_SESSION_KEY = "active_branch_id"


def _get_profile(user):
    return get_profile(user)


def _get_role(user):
    p = _get_profile(user)
    return getattr(p, "role", None)


def _is_admin_like(user) -> bool:
    return is_admin_user(user)


@login_required
def home(request):
    """
    Login'dan keyingi router:
      - admin-like -> branch tanlashi shart
      - cashier -> o'z branch'i avtomatik tanlanadi
    """
    if _is_admin_like(request.user):
        if request.session.get(ACTIVE_BRANCH_SESSION_KEY):
            return redirect("sales:pos_orders")
        return redirect("select_branch")

    prof = _get_profile(request.user)
    branch = getattr(prof, "branch", None) if prof else None
    if not getattr(branch, "is_active", False):
        return HttpResponseForbidden("Sizga faol filial biriktirilmagan. Admin bilan bog'laning.")
    request.session[ACTIVE_BRANCH_SESSION_KEY] = str(branch.id)
    return redirect("sales:pos_orders")


@login_required
@require_http_methods(["GET", "POST"])
def select_branch(request):
    if not _is_admin_like(request.user):
        return HttpResponseForbidden("Branch tanlash huquqi yo'q.")

    if request.method == "POST":
        branch_id = request.POST.get("branch_id")
        if not branch_id:
            return HttpResponseForbidden("branch_id required")

        ok = Branch.objects.filter(id=branch_id, is_active=True).exists()
        if not ok:
            return HttpResponseForbidden("Branch topilmadi yoki aktiv emas.")

        request.session[ACTIVE_BRANCH_SESSION_KEY] = str(branch_id)
        return redirect("sales:pos_orders")

    branches = Branch.objects.filter(is_active=True).order_by("name")
    return render(request, "core/select_branch.html", {"branches": branches})


@login_required
def dashboard(request):
    if not _is_admin_like(request.user):
        return redirect("sales:pos_orders")
    return render(request, "core/dashboard.html")
