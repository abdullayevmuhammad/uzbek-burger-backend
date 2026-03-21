from users.utils import get_profile, is_admin_user


def app_context(request):
    user = request.user
    prof = get_profile(user)

    role = getattr(prof, "role", None) if prof else None
    is_admin_like = bool(user.is_authenticated and is_admin_user(user))

    return {
        "active_branch": getattr(request, "active_branch", None),
        "is_admin_like": is_admin_like,
        "user_role": role,
        "user_profile": prof,
    }
