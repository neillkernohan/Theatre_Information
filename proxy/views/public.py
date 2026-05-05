from flask import render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from proxy import proxy_bp
from proxy.models import db, ProxyMeeting, ProxyMember, ProxySubmission
from proxy.forms import ProxyForm
from proxy.email import send_proxy_notification
from datetime import datetime


def get_current_member():
    """Return the ProxyMember record for the logged-in user, or None."""
    return ProxyMember.query.filter_by(
        email=current_user.email.lower(), is_active=True
    ).first()


# ---------------------------------------------------------------------------
# Landing / meeting list
# ---------------------------------------------------------------------------

@proxy_bp.route('/')
@login_required
def index():
    member = get_current_member()
    open_meetings = ProxyMeeting.query.filter_by(status='open').order_by(ProxyMeeting.meeting_date).all()
    past_meetings = (ProxyMeeting.query
                     .filter(ProxyMeeting.status != 'open')
                     .order_by(ProxyMeeting.meeting_date.desc())
                     .limit(5)
                     .all())

    my_active_proxy_ids = set()
    if member:
        my_active_proxy_ids = {
            s.meeting_id
            for s in ProxySubmission.query.filter_by(grantor_user_id=current_user.id, revoked=False).all()
        }

    return render_template('proxy/public/index.html',
                           member=member,
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
    member = get_current_member()

    if not member:
        flash('You are not registered as a Theatre Aurora member. Contact the secretary to be added.', 'warning')
        return redirect(url_for('proxy.index'))

    if not meeting.is_open:
        flash('This meeting is not currently accepting proxy submissions.', 'warning')
        return redirect(url_for('proxy.index'))

    existing = ProxySubmission.query.filter_by(
        meeting_id=meeting_id, grantor_user_id=current_user.id, revoked=False
    ).first()

    form = ProxyForm()
    # All active members except the current user (proxy holder must be a different member)
    holders = (ProxyMember.query
               .filter(ProxyMember.is_active == True, ProxyMember.id != member.id)
               .order_by(ProxyMember.last_name, ProxyMember.first_name)
               .all())
    form.holder_member_id.choices = [(h.id, h.full_name) for h in holders]

    if form.validate_on_submit():
        if existing:
            existing.revoked = True
            existing.revoked_at = datetime.utcnow()

        holder = ProxyMember.query.get(form.holder_member_id.data)
        submission = ProxySubmission(
            meeting_id=meeting_id,
            grantor_user_id=current_user.id,
            holder_member_id=holder.id,
            holder_name=holder.full_name,
            signature_name=form.signature_name.data.strip(),
        )
        db.session.add(submission)
        db.session.commit()

        if meeting.notify_email:
            send_proxy_notification(submission, meeting)

        flash('Your proxy has been submitted successfully.', 'success')
        return redirect(url_for('proxy.my_proxies'))

    return render_template('proxy/public/proxy_form.html',
                           form=form, meeting=meeting, member=member, existing=existing)


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
