from flask import render_template, url_for
from notifications.core import get_mail, send_logged_email


def _get_mail():
    """Get the Mail instance from the current app extensions.

    Thin wrapper kept so tests can patch ``auditions.email._get_mail``.
    """
    return get_mail()


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
    html_body = render_template(
        f'auditions/email/{template}.html',
        registration=registration,
        user=user,
        **kwargs
    )

    return send_logged_email(
        _get_mail(),
        to=to,
        subject=subject,
        html_body=html_body,
        email_type=template,
        registration_id=registration.id if registration else None,
        user_id=user.id if user else (registration.user_id if registration else None),
    )


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
        slot=slot,
        dashboard_url=url_for('auditions.actor_dashboard', _external=True),
        cancel_url=url_for('auditions.cancel_confirm', reg_id=registration.id, _external=True)
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
        show=show,
        dashboard_url=url_for('auditions.actor_dashboard', _external=True),
        cancel_url=url_for('auditions.cancel_confirm', reg_id=registration.id, _external=True)
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
        slot=slot,
        dashboard_url=url_for('auditions.actor_dashboard', _external=True),
        cancel_url=url_for('auditions.cancel_confirm', reg_id=registration.id, _external=True)
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


def send_password_reset_email(user, reset_url):
    """Send a password reset link to the user."""
    return send_email(
        to=user.email,
        subject='Reset Your Password — Theatre Aurora Auditions',
        template='password_reset',
        user=user,
        reset_url=reset_url
    )


def send_slot_changed_email(registration):
    """Send confirmation when an actor changes their audition time slot."""
    user = registration.user
    show = registration.show
    slot = registration.slot

    return send_email(
        to=user.email,
        subject=f'Audition Time Updated — {show.title}',
        template='slot_changed',
        registration=registration,
        user=user,
        show=show,
        slot=slot,
        dashboard_url=url_for('auditions.actor_dashboard', _external=True),
        cancel_url=url_for('auditions.cancel_confirm', reg_id=registration.id, _external=True)
    )


def send_admin_notification(registration, event):
    """
    Send a notification to all addresses in the show's notify_email field
    (comma-separated) when a registration is created, cancelled, or its
    status changes.

    event: a short string like 'New Registration', 'Cancelled', 'Status → callback'
    """
    notify_email = registration.show.notify_email
    if not notify_email:
        return  # No notification address configured for this show

    recipients = [a.strip() for a in notify_email.split(',') if a.strip()]
    if not recipients:
        return

    user = registration.user
    show = registration.show
    reg_url = url_for('auditions.registration_detail', reg_id=registration.id, _external=True)

    html_body = render_template(
        'auditions/email/admin_notification.html',
        registration=registration,
        user=user,
        show=show,
        event=event,
        reg_url=reg_url
    )

    send_logged_email(
        _get_mail(),
        to=recipients,
        subject=f'{event} — {user.first_name} {user.last_name} — {show.title}',
        html_body=html_body,
        email_type='admin_notification',
        registration_id=registration.id,
        user_id=registration.user_id,
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


def send_bulk_email(show, registrations, subject, body):
    """Send a custom message to a list of registrations.

    Returns a tuple (sent_count, failed_count).
    """
    from auth.models import db

    mail = _get_mail()
    sent = 0
    failed = 0

    for reg in registrations:
        user = reg.user
        if not user.contact_email_ok:
            continue

        html_body = render_template(
            'auditions/email/bulk_message.html',
            registration=reg,
            user=user,
            show=show,
            subject=subject,
            body=body,
        )

        # commit=False — log rows accumulate and are committed once after the loop.
        if send_logged_email(
            mail,
            to=user.email,
            subject=subject,
            html_body=html_body,
            email_type='bulk_message',
            registration_id=reg.id,
            user_id=user.id,
            commit=False,
        ):
            sent += 1
        else:
            failed += 1

    db.session.commit()
    return sent, failed
