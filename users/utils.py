# users/utils.py
from .models import StaffRole

def get_user_scope(user):
    """
    Returns:
      ("all", None) for owner
      ("branch", branch_id) for staff
    """
    prof = getattr(user, "profile", None)
    if not prof or not prof.is_active:
        return ("none", None)

    if prof.role == StaffRole.OWNER:
        return ("all", None)

    return ("branch", prof.branch_id)

from .models import StaffRole

def get_user_branch_id(user):
    prof = getattr(user, "profile", None)
    if not prof or not prof.is_active:
        return None
    if prof.role == StaffRole.OWNER:
        return None  # owner global
    return prof.branch_id
