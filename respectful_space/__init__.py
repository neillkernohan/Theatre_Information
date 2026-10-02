from flask import Blueprint

respectful_space_bp = Blueprint(
    'respectful_space',
    __name__,
    url_prefix='/respectful-space'
)

from respectful_space import views  # noqa: E402, F401
