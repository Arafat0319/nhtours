"""Admin role helpers: admin vs staff."""
from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def admin_required(view):
    """Require logged-in user with role=admin (sensitive money / delete / export)."""

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not getattr(current_user, "is_admin", False):
            abort(403)
        return view(*args, **kwargs)

    return wrapped
