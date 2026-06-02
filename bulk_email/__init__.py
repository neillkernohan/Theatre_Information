from flask import Blueprint

bulk_email_bp = Blueprint('bulk_email', __name__, url_prefix='/bulk-email')

from . import views  # noqa: E402, F401
