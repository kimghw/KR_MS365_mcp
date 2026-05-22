"""
Flask Routes Package

MCP Tool Editor의 모든 Flask 라우트를 포함합니다.
각 블루프린트는 특정 기능 영역을 담당합니다.
"""

from flask import Blueprint

# Create blueprints
tool_bp = Blueprint('tools', __name__)
backup_bp = Blueprint('backups', __name__)
profile_bp = Blueprint('profiles', __name__)
registry_bp = Blueprint('registry', __name__)
generator_bp = Blueprint('generator', __name__)
basemodel_bp = Blueprint('basemodel', __name__)
server_bp = Blueprint('server', __name__)
utility_bp = Blueprint('utility', __name__)

# Import routes to register them with blueprints
from . import tool_routes
from . import backup_routes
from . import profile_routes
from . import registry_routes
from . import generator_routes
from . import basemodel_routes
from . import server_routes
from . import utility_routes


def register_routes(app):
    """Register all blueprints with the Flask app"""
    app.register_blueprint(tool_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(registry_bp)
    app.register_blueprint(generator_bp)
    app.register_blueprint(basemodel_bp)
    app.register_blueprint(server_bp)
    app.register_blueprint(utility_bp)


__all__ = [
    'tool_bp',
    'backup_bp',
    'profile_bp',
    'registry_bp',
    'generator_bp',
    'basemodel_bp',
    'server_bp',
    'utility_bp',
    'register_routes',
]
