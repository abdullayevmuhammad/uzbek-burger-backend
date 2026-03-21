from .models import StaffRole

LEGACY_ADMIN_ROLES = {"owner"}
LEGACY_CASHIER_ROLES = {"staff"}


def get_profile(user):
    return getattr(user, "profile", None) or getattr(user, "staffprofile", None)


def is_active_profile(profile) -> bool:
    return bool(profile and getattr(profile, "is_active", False))


def is_admin_role_value(role: str | None) -> bool:
    return role in {StaffRole.ADMIN, *LEGACY_ADMIN_ROLES}


def is_cashier_role_value(role: str | None) -> bool:
    return role in {StaffRole.CASHIER, *LEGACY_CASHIER_ROLES}


def is_super_recovery_user(user) -> bool:
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "is_superuser", False))


def is_admin_user(user) -> bool:
    if is_super_recovery_user(user):
        return True
    profile = get_profile(user)
    return bool(is_active_profile(profile) and is_admin_role_value(getattr(profile, "role", None)))


def is_cashier_user(user) -> bool:
    profile = get_profile(user)
    return bool(is_active_profile(profile) and is_cashier_role_value(getattr(profile, "role", None)))


def can_access_admin(user) -> bool:
    return is_admin_user(user)


def get_user_scope(user):
    """
    Returns:
      ("all", None) for admin/superuser
      ("branch", branch_id) for cashier
      ("none", None) for inactive/unassigned
    """
    if is_super_recovery_user(user):
        return ("all", None)

    prof = get_profile(user)
    if not is_active_profile(prof):
        return ("none", None)

    if is_admin_role_value(prof.role):
        return ("all", None)

    return ("branch", prof.branch_id)


def get_user_branch_id(user):
    if is_super_recovery_user(user):
        return None
    prof = get_profile(user)
    if not is_active_profile(prof):
        return None
    if is_admin_role_value(prof.role):
        return None
    return prof.branch_id
