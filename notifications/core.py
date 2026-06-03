"""Shared email-sending helpers used by the auditions and proxy apps.

Centralises the "build Message → send → write EmailLog → commit" pattern so each
app only has to render its own HTML and supply recipients, subject, and a few
log fields.
"""
from flask import current_app
from flask_mail import Message
from datetime import datetime

from auth.models import db
from notifications.models import EmailLog


def get_mail():
    """Return the Flask-Mail instance registered on the current app."""
    return current_app.extensions['mail']


def send_logged_email(mail, *, to, subject, html_body, email_type,
                      registration_id=None, user_id=None, commit=True):
    """Send one HTML email and record the attempt in EmailLog.

    Args:
        mail: the Flask-Mail instance (passed in rather than fetched here so
            callers can supply a test double / patch their own ``_get_mail``).
        to: a single address or a list/tuple of addresses.
        subject: email subject line.
        html_body: pre-rendered HTML body.
        email_type: short tag stored on the log row (e.g. 'confirmation').
        registration_id / user_id: optional FK values for the log row.
        commit: when False, the log row is added to the session but not
            committed — let the caller commit once after a batch.

    Returns:
        True if the message was sent, False if sending raised.
    """
    recipients = list(to) if isinstance(to, (list, tuple)) else [to]
    msg = Message(subject=subject, recipients=recipients, html=html_body)

    log = EmailLog(
        registration_id=registration_id,
        user_id=user_id,
        email_type=email_type,
        sent_at=datetime.utcnow(),
    )

    sent = False
    try:
        mail.send(msg)
        log.status = 'sent'
        sent = True
    except Exception as e:
        log.status = 'failed'
        log.error_message = str(e)
        current_app.logger.error(f'Email send failed ({email_type}): {e}')

    db.session.add(log)
    if commit:
        db.session.commit()
    return sent
