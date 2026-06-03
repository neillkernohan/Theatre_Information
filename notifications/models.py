"""Shared models for cross-app notifications.

Currently just the email audit log, which is written by both the auditions and
proxy apps. It lived in ``auditions.models`` historically; it now lives here so
that proxy (and any future app) no longer has to reach across into auditions to
log an email.
"""
from auth.models import db
from datetime import datetime


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
