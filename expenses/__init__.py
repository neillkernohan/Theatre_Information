from flask import Blueprint

expenses_bp = Blueprint(
    'expenses',
    __name__,
    url_prefix='/expenses'
)

from expenses import cli  # noqa: E402, F401
from expenses.views import approvals, claims, home, payments, setup  # noqa: E402, F401
