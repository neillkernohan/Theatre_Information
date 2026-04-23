from flask import render_template, current_app
from flask_mail import Message
from auditions.models import db, EmailLog
from datetime import datetime


def _get_mail():
    """Get the Mail instance from the current app extensions."""
    return current_app.extensions['mail']


def send_email(to, subject, template, registration=None, user=None, **kwargs):
    """
    Send an HTML email using a template.

    Args:
        to: recipient email address
        subject: email subject line
        template: template path (without .html) under templates/auditions/email/
        registration: optional Registration object for logging
        user: optional User object for logging
        **kwargs: additional context passed to the template
    """
    mail = _get_mail()

    html_body = render_template(
        f'auditions/email/{template}.html',
        registration=registration,
        user=user,
        **kwargs
    )

    msg = Message(
        subject=subject,
        recipients=[to],
        html=html_body
    )

    # Log the attempt
    log = EmailLog(
        registration_id=registration.id if registration else None,
        user_id=user.id if user else (registration.user_id if registration else None),
        email_type=template,
        sent_at=datetime.utcnow()
    )

    try:
        mail.send(msg)
        log.status = 'sent'
    except Exception as e:
        log.status = 'failed'
        log.error_message = str(e)
        current_app.logger.error(f'Email send failed: {e}')

    db.session.add(log)
    db.session.commit()

    return log.status == 'sent'


def send_confirmation_email(registration):
    """Send registration confirmation email to the actor."""
    user = registration.user
    show = registration.show
    slot = registration.slot

    return send_email(
        to=user.email,
        subject=f'Audition Confirmed — {show.title}',
        template='confirmation',
        registration=registration,
        user=user,
        show=show,
        slot=slot
    )


def send_waitlist_email(registration):
    """Send waitlist notification email to the actor."""
    user = registration.user
    show = registration.show

    return send_email(
        to=user.email,
        subject=f'Waitlisted — {show.title}',
        template='waitlisted',
        registration=registration,
        user=user,
        show=show
    )


def send_callback_email(registration, callback_details=''):
    """Send callback notification email to the actor."""
    user = registration.user
    show = registration.show

    return send_email(
        to=user.email,
        subject=f'Callback — {show.title}',
        template='callback',
        registration=registration,
        user=user,
        show=show,
        callback_details=callback_details
    )


def send_reminder_email(registration):
    """Send audition reminder email (day before)."""
    user = registration.user
    show = registration.show
    slot = registration.slot

    return send_email(
        to=user.email,
        subject=f'Audition Reminder — {show.title} Tomorrow',
        template='reminder',
        registration=registration,
        user=user,
        show=show,
        slot=slot
    )


def send_info_request_email(registration, requested_items=None):
    """Send email requesting headshot/resume/video from an actor."""
    user = registration.user
    show = registration.show

    return send_email(
        to=user.email,
        subject=f'Materials Requested — {show.title}',
        template='info_request',
        registration=registration,
        user=user,
        show=show,
        requested_items=requested_items or []
    )


def send_cancellation_email(registration):
    """Send cancellation confirmation email to the actor."""
    user = registration.user
    show = registration.show

    return send_email(
        to=user.email,
        subject=f'Registration Cancelled — {show.title}',
        template='cancellation',
        registration=registration,
        user=user,
        show=show
    )
