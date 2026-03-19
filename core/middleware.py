from django.conf import settings
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse

from core.models import Branch
from users.models import StaffRole

ACTIVE_BRANCH_SESSION_KEY = "active_branch_id"


def _get_profile(user):
    return getattr(user, "profile", None) or getattr(user, "staffprofile", None)


def _get_role(user):
    profile = _get_profile(user)
    return getattr(profile, "role", None)


def _is_admin_like(user) -> bool:
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    role = getattr(profile, "role", None) if profile else None
    return role == StaffRole.OWNER


def _get_select_branch_path():
    try:
        return reverse("select_branch")
    except NoReverseMatch:
        return None


class ActiveBranchMiddleware:
    """
    request.active_branch:
      - admin-like: session'dan
      - staff: profile.branch'dan
    POS mode o'chirilgan bo'lsa middleware umuman ishlamaydi.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "POS_MODE", True):
            return self.get_response(request)

        if request.user.is_authenticated:
            path = request.path
            select_branch_path = _get_select_branch_path()

            exempt_prefixes = ("/accounts/", "/static/", "/media/", "/admin/")
            exempt_exact = tuple(p for p in (select_branch_path,) if p)

            if path.startswith(exempt_prefixes) or path in exempt_exact:
                return self.get_response(request)

            if _is_admin_like(request.user):
                branch_id = request.session.get(ACTIVE_BRANCH_SESSION_KEY)
                if not branch_id:
                    if select_branch_path:
                        return redirect(select_branch_path)
                    request.active_branch = None
                    return self.get_response(request)
                request.active_branch = Branch.objects.filter(id=branch_id).first()
            else:
                profile = _get_profile(request.user)
                request.active_branch = getattr(profile, "branch", None) if profile else None

        return self.get_response(request)


def get_active_branch(request):
    """Small helper (views can import it)."""
    return getattr(request, "active_branch", None)


class AdminGuardMiddleware:
    """Oddiy operatorlarni /admin/ ga kiritmaslik."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            user = getattr(request, "user", None)
            if user and user.is_authenticated:
                profile = getattr(user, "profile", None)
                role = getattr(profile, "role", None) if profile else None
                if not (user.is_superuser or role == StaffRole.OWNER):
                    return HttpResponseForbidden("Admin panel faqat admin uchun.")
        return self.get_response(request)
