from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

THEATREAURORA_DOMAIN = '@theatreaurora.com'


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)

    # Nullable — staff sign in via Google only and never have a password set.
    # Actors may use email/password or Google OAuth.
    password_hash = db.Column(db.String(255), nullable=True)

    # Set when a user first authenticates via Google.
    google_id = db.Column(db.String(255), unique=True, nullable=True)

    role = db.Column(
        db.Enum('admin', 'viewer', 'actor', name='user_role'),
        nullable=False,
        default='actor'
    )

    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)

    # Actor-specific contact & profile fields (NULL for staff)
    phone = db.Column(db.String(20))
    address = db.Column(db.String(255))
    city = db.Column(db.String(100))
    province = db.Column(db.String(100))
    postal_code = db.Column(db.String(20))
    pronouns = db.Column(db.String(50))
    contact_email_ok = db.Column(db.Boolean, default=True)
    roles_auditioning_for = db.Column(db.String(500))
    accept_other_role = db.Column(db.Boolean, default=True)
    comfortable_performing = db.Column(db.Boolean, default=True)
    equity_or_actra = db.Column(db.Boolean, default=False)
    schedule_conflicts = db.Column(db.Text)
    training = db.Column(db.Text)
    acting_experience = db.Column(db.JSON)
    volunteer_interests = db.Column(db.JSON)
    past_member = db.Column(db.Boolean)
    hear_about_us = db.Column(db.String(255))

    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    registrations = db.relationship('Registration', backref='user', lazy='dynamic')

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    @property
    def is_staff(self):
        """True for any @theatreaurora.com account (admin, viewer, or new auto-created)."""
        return self.email.endswith(THEATREAURORA_DOMAIN)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def touch_last_login(self):
        self.last_login = datetime.utcnow()

    def __repr__(self):
        return f'<User {self.first_name} {self.last_name} ({self.role})>'
