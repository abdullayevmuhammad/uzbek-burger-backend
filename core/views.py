from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from users.models import StaffRole

from core.models import Branch

ACTIVE_BRANCH_SESSION_KEY = "active_branch_id"


def _get_profile(user):
    # sende user.profile bo'lishi mumkin, yoki user.staffprofile
    return getattr(user, "profile", None) or getattr(user, "staffprofile", None)


def _get_role(user):
    p = _get_profile(user)
    return getattr(p, "role", None)



def _is_admin_like(user) -> bool:
    if user.is_superuser:
        return True
    prof = getattr(user, "profile", None)
    role = getattr(prof, "role", None) if prof else None
    return role == StaffRole.OWNER  # ✅ faqat owner


@login_required
def home(request):
    """
    Login'dan keyingi 'router':
      - admin-like -> branch tanlashi shart
      - staff -> o'z branch'i avtomatik tanlanadi
    """
    # Admin/owner/manager: branch tanlashga yuboramiz
    if _is_admin_like(request.user):
        if request.session.get(ACTIVE_BRANCH_SESSION_KEY):
            return redirect("sales:pos_orders")
        return redirect("select_branch")

    # Oddiy staff: o'z branch'ini avtomatik set qilamiz
    prof = _get_profile(request.user)
    branch_id = getattr(prof, "branch_id", None) if prof else None
    if not branch_id:
        return HttpResponseForbidden("Sizga branch biriktirilmagan. Admin bilan bog'laning.")
    request.session[ACTIVE_BRANCH_SESSION_KEY] = str(branch_id)
    return redirect("sales:pos_orders")


@login_required
@require_http_methods(["GET", "POST"])
def select_branch(request):
    # faqat admin-like tanlay oladi
    if not _is_admin_like(request.user):
        return HttpResponseForbidden("Branch tanlash huquqi yo'q.")

    if request.method == "POST":
        branch_id = request.POST.get("branch_id")
        if not branch_id:
            return HttpResponseForbidden("branch_id required")

        # faqat active branch tanlash
        ok = Branch.objects.filter(id=branch_id, is_active=True).exists()
        if not ok:
            return HttpResponseForbidden("Branch topilmadi yoki aktiv emas.")

        request.session[ACTIVE_BRANCH_SESSION_KEY] = str(branch_id)
        return redirect("sales:pos_orders")

    branches = Branch.objects.filter(is_active=True).order_by("name")
    return render(request, "core/select_branch.html", {"branches": branches})


@login_required
def dashboard(request):
    # faqat admin-like uchun (oddiy operatorga kerak emas)
    if not _is_admin_like(request.user):
        return redirect("sales:pos_orders")
    return render(request, "core/dashboard.html")
