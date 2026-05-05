from flask import render_template, redirect, url_for, flash, abort, current_app
from flask_login import login_required, current_user
from proxy import proxy_bp
from proxy.models import db, ProxyMeeting, ProxySubmission
from proxy.forms import ProxyForm
from proxy.email import send_proxy_notification
from datetime import datetime
import mysql.connector
import os


def _patron_db():
    """Open a connection to the Theatre_Information database."""
    return mysql.connector.connect(
        host=os.getenv('MYSQL_HOST'),
        user=os.getenv('MYSQL_USER'),
        password=os.getenv('MYSQL_PASSWORD'),
        database=os.getenv('MYSQL_DATABASE'),
    )


def is_current_user_member():
    """Return True if the logged-in user's email matches an active member in Patrons."""
    try:
        conn = _patron_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT is_member FROM Patrons WHERE LOWER(Email) = %s AND is_member = 1 LIMIT 1",
            (current_user.email.lower(),)
        )
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        current_app.logger.error(f'Member lookup failed: {e}')
        return False


def get_voting_members(exclude_email=None):
    """Return list of (full_name,) for all members eligible to hold a proxy."""
    try:
        conn = _patron_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT First_name, Last_name FROM Patrons WHERE is_member = 1 ORDER BY Last_name, First_name"
        )
        rows = cursor.fetchall()
        conn.close()
        members = []
        for first, last in rows:
            full = f"{first} {last}"
            if exclude_email and f"{first} {last}".lower() == exclude_email.lower():
                continue
            members.append(full)
        return members
    except Exception as e:
        current_app.logger.error(f'Member list lookup failed: {e}')
        return []


def current_user_full_name():
    return f"{current_user.first_name} {current_user.last_name}"


# ---------------------------------------------------------------------------
# Landing / meeting list
# ---------------------------------------------------------------------------

@proxy_bp.route('/')
@login_required
def index():
    is_member = is_current_user_member()
    open_meetings = ProxyMeeting.query.filter_by(status='open').order_by(ProxyMeeting.meeting_date).all()
    past_meetings = (ProxyMeeting.query
                     .filter(ProxyMeeting.status != 'open')
                     .order_by(ProxyMeeting.meeting_date.desc())
                     .limit(5)
                     .all())

    my_active_proxy_ids = {
        s.meeting_id
        for s in ProxySubmission.query.filter_by(grantor_user_id=current_user.id, revoked=False).all()
    }

    return render_template('proxy/public/index.html',
                           is_member=is_member,
                           open_meetings=open_meetings,
                           past_meetings=past_meetings,
                           my_active_proxy_ids=my_active_proxy_ids)


# ---------------------------------------------------------------------------
# Submit proxy
# ---------------------------------------------------------------------------

@proxy_bp.route('/meetings/<int:meeting_id>/proxy', methods=['GET', 'POST'])
@login_required
def submit_proxy(meeting_id):
    meeting = ProxyMeeting.query.get_or_404(meeting_id)

    if not is_current_user_member():
        flash('Your account is not registered as a Theatre Aurora member. Contact the secretary.', 'warning')
        return redirect(url_for('proxy.index'))

    if not meeting.is_open:
        flash('This meeting is not currently accepting proxy submissions.', 'warning')
        return redirect(url_for('proxy.index'))

    existing = ProxySubmission.query.filter_by(
        meeting_id=meeting_id, grantor_user_id=current_user.id, revoked=False
    ).first()

    form = ProxyForm()
    # All members except the current user
    my_name = current_user_full_name()
    holders = get_voting_members()
    holders = [h for h in holders if h.lower() != my_name.lower()]
    form.holder_name.choices = [(h, h) for h in holders]

    if form.validate_on_submit():
        if existing:
            existing.revoked = True
            existing.revoked_at = datetime.utcnow()

        submission = ProxySubmission(
            meeting_id=meeting_id,
            grantor_user_id=current_user.id,
            holder_name=form.holder_name.data,
            signature_name=form.signature_name.data.strip(),
        )
        db.session.add(submission)
        db.session.commit()

        if meeting.notify_email:
            send_proxy_notification(submission, meeting)

        flash('Your proxy has been submitted successfully.', 'success')
        return redirect(url_for('proxy.my_proxies'))

    return render_template('proxy/public/proxy_form.html',
                           form=form, meeting=meeting, existing=existing,
                           my_name=my_name)


# ---------------------------------------------------------------------------
# My proxies
# ---------------------------------------------------------------------------

@proxy_bp.route('/my-proxies')
@login_required
def my_proxies():
    submissions = (ProxySubmission.query
                   .filter_by(grantor_user_id=current_user.id)
                   .order_by(ProxySubmission.submitted_at.desc())
                   .all())
    return render_template('proxy/public/my_proxies.html', submissions=submissions)


@proxy_bp.route('/proxy/<int:submission_id>/revoke', methods=['POST'])
@login_required
def revoke_proxy(submission_id):
    submission = ProxySubmission.query.get_or_404(submission_id)
    if submission.grantor_user_id != current_user.id:
        abort(403)
    if submission.revoked:
        flash('This proxy has already been revoked.', 'warning')
    elif not submission.meeting.is_open:
        flash('The proxy deadline has passed — contact the secretary to revoke this proxy.', 'warning')
    else:
        submission.revoked = True
        submission.revoked_at = datetime.utcnow()
        db.session.commit()
        flash('Your proxy has been revoked.', 'success')
    return redirect(url_for('proxy.my_proxies'))
