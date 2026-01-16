from users.models import StaffRole

def app_context(request):
    user = request.user
    prof = getattr(user, "profile", None)

    role = getattr(prof, "role", None) if prof else None
    is_admin_like = bool(user.is_authenticated and (user.is_superuser or role == StaffRole.OWNER))

    return {
        "active_branch": getattr(request, "active_branch", None),
        "is_admin_like": is_admin_like,
        "user_role": role,
        "user_profile": prof,
    }
