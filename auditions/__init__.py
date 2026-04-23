from flask import Blueprint

auditions_bp = Blueprint(
    'auditions',
    __name__,
    static_folder='../static/auditions',
    url_prefix='/auditions'
)

from auditions.views import auth, admin, public, export  # noqa: E402, F401
