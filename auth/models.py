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
        db.Enum(
            'super_admin', 'auditions_creator', 'director', 'producer', 'stage_manager',
            'admin',   # legacy alias for super_admin
            'viewer',  # legacy alias for stage_manager
            'actor',
            name='user_role'
        ),
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

    # NULL = super admin (all shows); [1, 2, ...] = restricted to those show IDs
    managed_shows = db.Column(db.JSON, nullable=True)

    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ------------------------------------------------------------------
    # Permission helpers
    # ------------------------------------------------------------------

    # Roles grouped by capability (legacy names kept for compat)
    _MANAGE_SHOWS  = {'super_admin', 'admin', 'auditions_creator'}
    _EVALUATE      = {'super_admin', 'admin', 'auditions_creator', 'director'}
    _CAN_EXPORT    = {'super_admin', 'admin', 'auditions_creator', 'director', 'producer'}
    _READ_ADMIN    = {'super_admin', 'admin', 'auditions_creator', 'director',
                      'producer', 'stage_manager', 'viewer'}
    _SUPER_ADMIN   = {'super_admin', 'admin'}

    @property
    def can_manage_shows(self):
        """Create/edit shows, manage slots, register/cancel actors."""
        return self.role in self._MANAGE_SHOWS

    @property
    def can_evaluate(self):
        """Add notes, photos, tags, callbacks, change status."""
        return self.role in self._EVALUATE

    @property
    def can_export(self):
        """Download Excel/Word exports."""
        return self.role in self._CAN_EXPORT

    @property
    def can_read_admin(self):
        """View admin dashboard, show detail, registration detail."""
        return self.role in self._READ_ADMIN

    @property
    def is_super_admin(self):
        """Full access including user/admin management."""
        return self.role in self._SUPER_ADMIN and not self.managed_shows

    @property
    def role_display(self):
        labels = {
            'super_admin': 'Super Admin',
            'admin': 'Super Admin',
            'auditions_creator': 'Auditions Creator',
            'director': 'Director',
            'producer': 'Producer',
            'stage_manager': 'Stage Manager',
            'viewer': 'Stage Manager',
            'actor': 'Actor',
        }
        return labels.get(self.role, self.role.replace('_', ' ').title())

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
