from auth.models import db
from datetime import datetime
import json


class SenderAccount(db.Model):
    __tablename__ = 'bulk_email_sender_accounts'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    display_name = db.Column(db.String(255))
    # Stored as JSON: {access_token, refresh_token, token_uri, client_id, client_secret, scopes}
    token_json = db.Column(db.Text, nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    campaigns = db.relationship('EmailCampaign', backref='sender', lazy='dynamic')

    def get_token_data(self):
        return json.loads(self.token_json)

    def set_token_data(self, data):
        self.token_json = json.dumps(data)

    def __repr__(self):
        return f'<SenderAccount {self.email}>'


AUDIENCE_LABELS = {
    'all_opted_in':       'All opted-in patrons',
    'ticket_buyers_2018': 'Ticket buyers since 2018 (opted in)',
    'members':            'Current members (opted in)',
    'volunteers':         'Volunteers mailing list (opted in)',
    'marketing_list':     'Custom marketing list',
    'season_buyers':      'Ticket buyers for a season',
    'specific_addresses': 'Specific email addresses',
}


class EmailCampaign(db.Model):
    __tablename__ = 'bulk_email_campaigns'

    id = db.Column(db.Integer, primary_key=True)
    sender_account_id = db.Column(db.Integer, db.ForeignKey('bulk_email_sender_accounts.id'), nullable=False)
    subject = db.Column(db.String(500), nullable=False)
    body_html = db.Column(db.Text, nullable=False)
    audience_type = db.Column(db.String(50), nullable=False)
    audience_params = db.Column(db.Text)  # JSON for parameterised audiences
    status = db.Column(
        db.Enum('draft', 'sending', 'paused', 'completed', 'failed', name='campaign_status'),
        default='draft'
    )
    total_count = db.Column(db.Integer, default=0)
    sent_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    opened_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    recipients = db.relationship('EmailRecipient', backref='campaign', lazy='dynamic',
                                 cascade='all, delete-orphan')

    @property
    def audience_label(self):
        return AUDIENCE_LABELS.get(self.audience_type, self.audience_type)

    @property
    def audience_params_dict(self):
        if self.audience_params:
            return json.loads(self.audience_params)
        return {}

    def __repr__(self):
        return f'<EmailCampaign {self.id} {self.subject[:30]}>'


class EmailRecipient(db.Model):
    __tablename__ = 'bulk_email_recipients'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('bulk_email_campaigns.id'), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    status = db.Column(
        db.Enum('pending', 'sent', 'failed', name='recipient_status'),
        default='pending'
    )
    error_message = db.Column(db.Text)
    sent_at = db.Column(db.DateTime)
    tracking_token = db.Column(db.String(32), unique=True, index=True)
    opened_at = db.Column(db.DateTime)   # first open
    open_count = db.Column(db.Integer, default=0)
