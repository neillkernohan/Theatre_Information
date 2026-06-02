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


# ---------------------------------------------------------------------------
# Auditions role-based decorators
# ---------------------------------------------------------------------------

def read_admin_required(f):
    """Any staff role — view dashboard, show detail, registration detail."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.can_read_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def evaluate_required(f):
    """Director and above — notes, photos, tags, callbacks, status changes."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.can_evaluate:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def manage_shows_required(f):
    """Auditions Creator and above — create/edit shows, manage slots & registrations."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.can_manage_shows:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def export_required(f):
    """Producer and above — download Excel/Word exports."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.can_export:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def inventory_required(f):
    """Inventory Manager and above — view and edit inventory."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.can_access_inventory:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Legacy aliases (keep existing code working during transition)
# ---------------------------------------------------------------------------

def admin_required(f):
    """Legacy alias → manage_shows_required."""
    return manage_shows_required(f)


def viewer_required(f):
    """Legacy alias → read_admin_required."""
    return read_admin_required(f)
