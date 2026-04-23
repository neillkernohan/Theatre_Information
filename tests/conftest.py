"""
Shared fixtures for the Auditions Manager test suite.

Uses an isolated SQLite in-memory database so tests never touch
the production MySQL instance.
"""
import os
import pytest
from datetime import datetime, timedelta
from flask import Flask
from flask_login import LoginManager
from flask_mail import Mail

# Point to project templates folder
TEMPLATES = os.path.join(os.path.dirname(__file__), '..', 'templates')


@pytest.fixture(scope='session')
def app():
    """Minimal Flask app wired with the auditions blueprint and SQLite."""
    flask_app = Flask(__name__, template_folder=TEMPLATES)
    flask_app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'SECRET_KEY': 'test-secret-key',
        'WTF_CSRF_ENABLED': False,
        'MAIL_SUPPRESS_SEND': True,
        'MAIL_SERVER': 'localhost',
        'MAIL_PORT': 25,
        'MAIL_DEFAULT_SENDER': 'test@theatreaurora.com',
        'SERVER_NAME': 'localhost',
    })

    from auditions.models import db, User
    db.init_app(flask_app)

    login_manager = LoginManager(flask_app)
    login_manager.login_view = 'auditions.actor_login'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    Mail(flask_app)

    # Register CSRFProtect so csrf_token() is available in templates;
    # actual validation is disabled via WTF_CSRF_ENABLED = False
    from flask_wtf.csrf import CSRFProtect
    CSRFProtect(flask_app)

    from auditions import auditions_bp
    flask_app.register_blueprint(auditions_bp)

    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.drop_all()


@pytest.fixture(scope='function')
def db(app):
    """Provide db and roll back after each test."""
    from auditions.models import db as _db
    with app.app_context():
        yield _db
        _db.session.rollback()
        # Clean all tables between tests
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()


@pytest.fixture(scope='function')
def client(app, db):
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def actor(db):
    from auditions.models import User
    u = User(
        email='actor@example.com',
        first_name='Jane',
        last_name='Smith',
        role='actor',
        contact_email_ok=True,
        accept_other_role=True,
        comfortable_performing=True,
        equity_or_actra=False,
    )
    u.set_password('ActorPass1!')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def admin(db):
    from auditions.models import User
    u = User(
        email='admin@theatreaurora.com',
        first_name='Admin',
        last_name='User',
        role='admin',
        contact_email_ok=True,
        accept_other_role=False,
        comfortable_performing=False,
        equity_or_actra=False,
    )
    u.set_password('AdminPass1!')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def slot_show(db):
    """Open show in slot mode with actor choice enabled."""
    from auditions.models import Show
    now = datetime.utcnow()
    show = Show(
        title='Test Slot Show',
        scheduling_mode='slot',
        slot_duration_minutes=15,
        allow_choice=True,
        registration_open=now - timedelta(days=1),
        registration_close=now + timedelta(days=30),
        status='open',
    )
    db.session.add(show)
    db.session.commit()
    return show


@pytest.fixture
def block_show(db):
    """Open show in block mode."""
    from auditions.models import Show
    now = datetime.utcnow()
    show = Show(
        title='Test Block Show',
        scheduling_mode='block',
        max_per_block=5,
        block_duration_minutes=90,
        allow_choice=False,
        registration_open=now - timedelta(days=1),
        registration_close=now + timedelta(days=30),
        status='open',
    )
    db.session.add(show)
    db.session.commit()
    return show


@pytest.fixture
def slot(db, slot_show):
    """A single available audition slot."""
    from auditions.models import AuditionSlot
    from datetime import date, time
    s = AuditionSlot(
        show_id=slot_show.id,
        date=date(2026, 6, 1),
        start_time=time(19, 0),
        end_time=time(19, 15),
        capacity=1,
        current_count=0,
    )
    db.session.add(s)
    db.session.commit()
    return s


# ---------------------------------------------------------------------------
# Login helpers
# ---------------------------------------------------------------------------

def login_as(client, email, password):
    return client.post('/auditions/login', data={
        'email': email,
        'password': password,
        'submit': 'Log In',
    }, follow_redirects=True)


def login_actor(client, actor):
    return login_as(client, actor.email, 'ActorPass1!')


def login_admin(client, admin):
    return login_as(client, admin.email, 'AdminPass1!')
