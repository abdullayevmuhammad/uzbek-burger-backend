from django.shortcuts import redirect
from django.http import HttpResponseForbidden
from django.urls import reverse

from core.models import Branch

from users.models import StaffRole

ACTIVE_BRANCH_SESSION_KEY = "active_branch_id"


def _get_profile(user):
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

class ActiveBranchMiddleware:
    """
    request.active_branch:
      - admin-like: session'dan
      - staff: profile.branch'dan
    Admin-like branch tanlamagan bo'lsa, select-branch sahifasiga majbur qiladi.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            path = request.path

            # ozod yo'llar (login/logout/static/select-branch)
            exempt_prefixes = ("/accounts/", "/static/", "/media/", "/admin/")
            exempt_exact = (reverse("select_branch"),)

            if path.startswith(exempt_prefixes) or path in exempt_exact:
                return self.get_response(request)

            if _is_admin_like(request.user):
                branch_id = request.session.get(ACTIVE_BRANCH_SESSION_KEY)
                if not branch_id:
                    return redirect("select_branch")
                request.active_branch = Branch.objects.filter(id=branch_id).first()
            else:
                prof = _get_profile(request.user)
                request.active_branch = getattr(prof, "branch", None) if prof else None

        return self.get_response(request)


def get_active_branch(request):
    """Small helper (views can import it)."""
    return getattr(request, "active_branch", None)


class AdminGuardMiddleware:
    """Oddiy operatorlarni /admin/ ga kiritmaslik.

    Eslatma: Django adminning o'zi ham is_staff tekshiradi, lekin biz role bo'yicha ham qo'shimcha chek qo'yamiz.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            user = getattr(request, "user", None)
            if user and user.is_authenticated:
                prof = getattr(user, "profile", None)
                role = getattr(prof, "role", None) if prof else None
                if not (user.is_superuser or role == StaffRole.OWNER):
                    return HttpResponseForbidden("Admin panel faqat admin uchun.")
        return self.get_response(request)

