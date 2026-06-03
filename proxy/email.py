from flask import render_template, url_for
from notifications.core import get_mail, send_logged_email


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

    send_logged_email(
        get_mail(),
        to=meeting.notify_email,
        subject=f'Proxy Submitted — {grantor.first_name} {grantor.last_name} — {meeting.title}',
        html_body=html_body,
        email_type='proxy_submitted',
        user_id=grantor.id,
    )


def send_proxy_admin_notification(submission, meeting):
    """Alias kept for import compatibility."""
    send_proxy_notification(submission, meeting)
