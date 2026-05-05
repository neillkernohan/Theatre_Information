from flask import render_template, redirect, url_for, flash, request, make_response, abort
from flask_login import login_required, current_user
from proxy import proxy_bp
from proxy.models import db, ProxyMeeting, ProxyMember, ProxySubmission
from proxy.forms import MeetingForm, MemberForm
from auth.decorators import admin_required
import csv
import io


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

@proxy_bp.route('/admin/')
@admin_required
def admin_dashboard():
    meetings = ProxyMeeting.query.order_by(ProxyMeeting.meeting_date.desc()).all()
    member_count = ProxyMember.query.filter_by(is_active=True).count()
    return render_template('proxy/admin/dashboard.html', meetings=meetings, member_count=member_count)


# ---------------------------------------------------------------------------
# Meeting management
# ---------------------------------------------------------------------------

@proxy_bp.route('/admin/meetings/new', methods=['GET', 'POST'])
@admin_required
def create_meeting():
    form = MeetingForm()
    if form.validate_on_submit():
        meeting = ProxyMeeting(
            title=form.title.data.strip(),
            meeting_date=form.meeting_date.data,
            proxy_deadline=form.proxy_deadline.data,
            description=form.description.data.strip() if form.description.data else None,
            notify_email=form.notify_email.data.strip() if form.notify_email.data else None,
            status=form.status.data,
        )
        db.session.add(meeting)
        db.session.commit()
        flash(f'Meeting "{meeting.title}" created.', 'success')
        return redirect(url_for('proxy.meeting_detail', meeting_id=meeting.id))
    return render_template('proxy/admin/meeting_form.html', form=form, meeting=None)


@proxy_bp.route('/admin/meetings/<int:meeting_id>')
@admin_required
def meeting_detail(meeting_id):
    meeting = ProxyMeeting.query.get_or_404(meeting_id)
    submissions = (ProxySubmission.query
                   .filter_by(meeting_id=meeting_id)
                   .order_by(ProxySubmission.submitted_at.desc())
                   .all())
    active_count = sum(1 for s in submissions if not s.revoked)
    return render_template('proxy/admin/meeting_detail.html',
                           meeting=meeting, submissions=submissions, active_count=active_count)


@proxy_bp.route('/admin/meetings/<int:meeting_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_meeting(meeting_id):
    meeting = ProxyMeeting.query.get_or_404(meeting_id)
    form = MeetingForm(obj=meeting)
    if form.validate_on_submit():
        meeting.title = form.title.data.strip()
        meeting.meeting_date = form.meeting_date.data
        meeting.proxy_deadline = form.proxy_deadline.data
        meeting.description = form.description.data.strip() if form.description.data else None
        meeting.notify_email = form.notify_email.data.strip() if form.notify_email.data else None
        meeting.status = form.status.data
        db.session.commit()
        flash('Meeting updated.', 'success')
        return redirect(url_for('proxy.meeting_detail', meeting_id=meeting.id))
    return render_template('proxy/admin/meeting_form.html', form=form, meeting=meeting)


@proxy_bp.route('/admin/meetings/<int:meeting_id>/export')
@admin_required
def export_proxies(meeting_id):
    meeting = ProxyMeeting.query.get_or_404(meeting_id)
    submissions = (ProxySubmission.query
                   .filter_by(meeting_id=meeting_id)
                   .order_by(ProxySubmission.submitted_at)
                   .all())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Grantor Name', 'Grantor Email', 'Proxy Holder', 'Submitted At', 'Revoked', 'Signature'])
    for s in submissions:
        writer.writerow([
            f'{s.grantor.first_name} {s.grantor.last_name}',
            s.grantor.email,
            s.holder_name,
            s.submitted_at.strftime('%Y-%m-%d %H:%M'),
            'Yes' if s.revoked else 'No',
            s.signature_name,
        ])

    response = make_response(output.getvalue())
    safe_title = meeting.title.replace(' ', '_')
    response.headers['Content-Disposition'] = f'attachment; filename=proxies_{safe_title}.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response


# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------

@proxy_bp.route('/admin/members')
@admin_required
def members_list():
    members = ProxyMember.query.order_by(ProxyMember.last_name, ProxyMember.first_name).all()
    return render_template('proxy/admin/members.html', members=members)


@proxy_bp.route('/admin/members/new', methods=['GET', 'POST'])
@admin_required
def add_member():
    form = MemberForm()
    if form.validate_on_submit():
        existing = ProxyMember.query.filter_by(email=form.email.data.strip().lower()).first()
        if existing:
            flash('A member with that email already exists.', 'danger')
        else:
            member = ProxyMember(
                first_name=form.first_name.data.strip(),
                last_name=form.last_name.data.strip(),
                email=form.email.data.strip().lower(),
                is_active=form.is_active.data,
            )
            db.session.add(member)
            db.session.commit()
            flash(f'{member.full_name} added to member list.', 'success')
            return redirect(url_for('proxy.members_list'))
    return render_template('proxy/admin/member_form.html', form=form, member=None)


@proxy_bp.route('/admin/members/<int:member_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_member(member_id):
    member = ProxyMember.query.get_or_404(member_id)
    form = MemberForm(obj=member)
    if form.validate_on_submit():
        conflict = ProxyMember.query.filter(
            ProxyMember.email == form.email.data.strip().lower(),
            ProxyMember.id != member_id
        ).first()
        if conflict:
            flash('Another member already has that email.', 'danger')
        else:
            member.first_name = form.first_name.data.strip()
            member.last_name = form.last_name.data.strip()
            member.email = form.email.data.strip().lower()
            member.is_active = form.is_active.data
            db.session.commit()
            flash('Member updated.', 'success')
            return redirect(url_for('proxy.members_list'))
    return render_template('proxy/admin/member_form.html', form=form, member=member)
