import os
from flask import Blueprint

auditions_bp = Blueprint(
    'auditions',
    __name__,
    static_folder='../static/auditions',
    url_prefix='/auditions'
)


@auditions_bp.context_processor
def inject_api_keys():
    return {'google_maps_api_key': os.getenv('GOOGLE_MAPS_API_KEY', '')}


from auditions.views import auth, admin, public, export  # noqa: E402, F401
