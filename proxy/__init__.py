from flask import Blueprint

proxy_bp = Blueprint(
    'proxy',
    __name__,
    url_prefix='/proxy'
)

from proxy.views import admin, public  # noqa: E402, F401
