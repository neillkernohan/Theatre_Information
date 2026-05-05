from flask import render_template, current_app, url_for
from flask_mail import Message
from auditions.models import db, EmailLog
from datetime import datetime


def _get_mail():
    return current_app.extensions['mail']


def send_proxy_notification(submission, meeting):
    """Email the meeting's notify_email when a proxy is submitted."""
    if not meeting.notify_email:
        return

    grantor = submission.grantor
    html_body = render_template(
        'proxy/email/proxy_submitted.html',
        submission=submission,
        meeting=meeting,
        grantor=grantor,
        admin_url=url_for('proxy.meeting_detail', meeting_id=meeting.id, _external=True)
    )

    mail = _get_mail()
    msg = Message(
        subject=f'Proxy Submitted — {grantor.first_name} {grantor.last_name} — {meeting.title}',
        recipients=[meeting.notify_email],
        html=html_body
    )

    log = EmailLog(
        user_id=grantor.id,
        email_type='proxy_submitted',
        sent_at=datetime.utcnow()
    )

    try:
        mail.send(msg)
        log.status = 'sent'
    except Exception as e:
        log.status = 'failed'
        log.error_message = str(e)
        current_app.logger.error(f'Proxy notification email failed: {e}')

    db.session.add(log)
    db.session.commit()


def send_proxy_admin_notification(submission, meeting):
    """Alias kept for import compatibility."""
    send_proxy_notification(submission, meeting)
