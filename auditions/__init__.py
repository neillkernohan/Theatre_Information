import os
from flask import Blueprint

auditions_bp = Blueprint(
    'auditions',
    __name__,
    static_folder='../static/auditions',
    url_prefix='/auditions'
)


@auditions_bp.context_processor
def inject_canada_post_key():
    return {'canada_post_api_key': os.getenv('CANADA_POST_API_KEY', '')}


from auditions.views import auth, admin, public, export  # noqa: E402, F401
