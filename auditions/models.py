from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum('admin', 'actor', name='user_role'), nullable=False, default='actor')
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
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
    acting_experience = db.Column(db.JSON)  # List of {show, role, theatre_group}
    volunteer_interests = db.Column(db.JSON)  # List of role strings
    past_member = db.Column(db.Boolean)
    hear_about_us = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    registrations = db.relationship('Registration', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.first_name} {self.last_name} ({self.role})>'


class Show(db.Model):
    __tablename__ = 'shows'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    audition_dates = db.Column(db.JSON)
    registration_open = db.Column(db.DateTime)
    registration_close = db.Column(db.DateTime)
    scheduling_mode = db.Column(db.Enum('block', 'slot', name='scheduling_mode'), nullable=False)
    slot_duration_minutes = db.Column(db.Integer)
    max_per_block = db.Column(db.Integer)
    block_duration_minutes = db.Column(db.Integer, default=90)
    allow_choice = db.Column(db.Boolean, default=True)
    custom_fields = db.Column(db.JSON)
    status = db.Column(db.Enum('draft', 'open', 'closed', 'archived', name='show_status'), default='draft')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    slots = db.relationship('AuditionSlot', backref='show', lazy='dynamic', cascade='all, delete-orphan')
    registrations = db.relationship('Registration', backref='show', lazy='dynamic')

    def __repr__(self):
        return f'<Show {self.title}>'


class AuditionSlot(db.Model):
    __tablename__ = 'audition_slots'

    id = db.Column(db.Integer, primary_key=True)
    show_id = db.Column(db.Integer, db.ForeignKey('shows.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    capacity = db.Column(db.Integer, nullable=False, default=1)
    current_count = db.Column(db.Integer, default=0)
    slot_type = db.Column(db.String(20), nullable=False, default='individual')
    label = db.Column(db.String(100))

    registrations = db.relationship('Registration', backref='slot', lazy='dynamic')

    @property
    def is_full(self):
        if self.slot_type == 'reserved':
            return True
        return self.current_count >= self.capacity

    def __repr__(self):
        return f'<AuditionSlot {self.date} {self.start_time}-{self.end_time}>'


registration_tags = db.Table(
    'registration_tags',
    db.Column('registration_id', db.Integer, db.ForeignKey('registrations.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id'), primary_key=True)
)


class Registration(db.Model):
    __tablename__ = 'registrations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    show_id = db.Column(db.Integer, db.ForeignKey('shows.id'), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey('audition_slots.id'), nullable=True)
    status = db.Column(
        db.Enum('confirmed', 'waitlisted', 'callback', 'cancelled', name='registration_status'),
        default='confirmed'
    )
    roles_auditioning_for = db.Column(db.String(500))
    accept_other_role = db.Column(db.Boolean)
    schedule_conflicts = db.Column(db.Text)
    headshot_path = db.Column(db.String(500))
    resume_path = db.Column(db.String(500))
    video_link = db.Column(db.String(500))
    custom_field_data = db.Column(db.JSON)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tags = db.relationship('Tag', secondary=registration_tags, backref='registrations')

    def __repr__(self):
        return f'<Registration {self.user.first_name} for {self.show.title}>'


class Tag(db.Model):
    __tablename__ = 'tags'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

    def __repr__(self):
        return f'<Tag {self.name}>'


class EmailLog(db.Model):
    __tablename__ = 'email_logs'

    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('registrations.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    email_type = db.Column(db.String(50), nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.Enum('sent', 'failed', 'pending', name='email_status'), default='pending')
    error_message = db.Column(db.Text)

    def __repr__(self):
        return f'<EmailLog {self.email_type} {self.status}>'
