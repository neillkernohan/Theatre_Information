from functools import wraps
from flask import abort
from flask_login import login_required, current_user

THEATREAURORA_DOMAIN = '@theatreaurora.com'


def theatreaurora_required(f):
    """Require the user to be logged in with a @theatreaurora.com email."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.email.endswith(THEATREAURORA_DOMAIN):
            abort(403)
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Require admin role."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated


def viewer_required(f):
    """Require admin or viewer role (read-only access)."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role not in ('admin', 'viewer'):
            abort(403)
        return f(*args, **kwargs)
    return decorated
