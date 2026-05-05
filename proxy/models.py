from auditions.models import db
from datetime import datetime


class ProxyMember(db.Model):
    __tablename__ = 'proxy_members'

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    proxies_held = db.relationship('ProxySubmission', foreign_keys='ProxySubmission.holder_member_id',
                                   backref='holder_member', lazy='dynamic')

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    def __repr__(self):
        return f'<ProxyMember {self.full_name}>'


class ProxyMeeting(db.Model):
    __tablename__ = 'proxy_meetings'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    meeting_date = db.Column(db.DateTime, nullable=False)
    proxy_deadline = db.Column(db.DateTime, nullable=False)
    description = db.Column(db.Text)
    notify_email = db.Column(db.String(255))
    status = db.Column(
        db.Enum('draft', 'open', 'closed', name='proxy_meeting_status'),
        default='draft'
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    submissions = db.relationship('ProxySubmission', backref='meeting', lazy='dynamic',
                                  cascade='all, delete-orphan')

    @property
    def is_open(self):
        return self.status == 'open' and datetime.utcnow() <= self.proxy_deadline

    def __repr__(self):
        return f'<ProxyMeeting {self.title}>'


class ProxySubmission(db.Model):
    __tablename__ = 'proxy_submissions'

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey('proxy_meetings.id'), nullable=False)
    grantor_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    holder_member_id = db.Column(db.Integer, db.ForeignKey('proxy_members.id'), nullable=False)
    holder_name = db.Column(db.String(255), nullable=False)
    signature_name = db.Column(db.String(255), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    revoked = db.Column(db.Boolean, default=False)
    revoked_at = db.Column(db.DateTime)

    grantor = db.relationship('User', foreign_keys=[grantor_user_id])

    def __repr__(self):
        return f'<ProxySubmission {self.grantor.first_name} → {self.holder_name}>'
