from flask import render_template, abort, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from auditions import auditions_bp
from auditions.models import db, Show, AuditionSlot, Registration, Tag, User, RegistrationFile, RegistrationPersonalNote
from datetime import datetime
from auditions.forms import ShowForm, GenerateSlotsForm
from auditions.utils import generate_slots, add_slots, promote_from_waitlist
from auditions.email import (
    send_callback_email, send_info_request_email,
    send_confirmation_email, send_waitlist_email, send_cancellation_email, send_admin_notification
)
from auth.decorators import (
    admin_required, viewer_required,
    read_admin_required, evaluate_required, manage_shows_required, export_required
)
import json
import os


# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------

def user_can_access_show(show_id):
    """Return True if the current user is allowed to access a show."""
    if not current_user.can_read_admin:
        return False
    # Super admins and viewers/stage managers see everything
    if current_user.is_super_admin or not current_user.managed_shows:
        return True
    return show_id in current_user.managed_shows


def shows_for_current_user():
    """Return the Show queryset filtered to what the current user may see."""
    if current_user.managed_shows:
        return Show.query.filter(Show.id.in_(current_user.managed_shows))
    return Show.query


# ---------------------------------------------------------------------------
# Dashboard & Show Management
# ---------------------------------------------------------------------------

@auditions_bp.route('/admin/dashboard')
@read_admin_required
def admin_dashboard():
    shows = shows_for_current_user().order_by(Show.created_at.desc()).all()

    # Admin management data — super admins only
    all_admins = None
    all_shows = None
    if current_user.is_super_admin:
        staff_roles = ('super_admin', 'admin', 'auditions_creator', 'director',
                       'producer', 'stage_manager', 'viewer')
        all_admins = User.query.filter(User.role.in_(staff_roles)).order_by(
            User.last_name, User.first_name
        ).all()
        all_shows = Show.query.order_by(Show.title).all()

    return render_template(
        'auditions/admin/dashboard.html',
        shows=shows,
        all_admins=all_admins,
        all_shows=all_shows,
    )


@auditions_bp.route('/admin/shows/new', methods=['GET', 'POST'])
@manage_shows_required
def create_show():
    form = ShowForm()
    if form.validate_on_submit():
        show = Show(
            title=form.title.data.strip(),
            description=form.description.data.strip() if form.description.data else None,
            scheduling_mode=form.scheduling_mode.data,
            allow_choice=form.allow_choice.data,
            registration_open=form.registration_open.data,
            registration_close=form.registration_close.data,
            status='draft'
        )

        if form.scheduling_mode.data == 'block':
            show.max_per_block = form.max_per_block.data or 10
            show.block_duration_minutes = form.block_duration_minutes.data or 90
        else:
            show.slot_duration_minutes = int(form.slot_duration_minutes.data)

        custom_fields_json = request.form.get('custom_fields_json', '[]')
        try:
            show.custom_fields = json.loads(custom_fields_json)
        except (json.JSONDecodeError, TypeError):
            show.custom_fields = []

        roles_json = request.form.get('roles_json', '[]')
        try:
            show.roles = [r.strip() for r in json.loads(roles_json) if r.strip()]
        except (json.JSONDecodeError, TypeError):
            show.roles = []

        show.notify_email = form.notify_email.data.strip() if form.notify_email.data else None

        db.session.add(show)
        db.session.commit()
        flash(f'Show "{show.title}" created. Now add audition dates and generate slots.', 'success')
        return redirect(url_for('auditions.show_detail', show_id=show.id))

    return render_template('auditions/admin/show_form.html', form=form, editing=False)


@auditions_bp.route('/admin/shows/<int:show_id>/edit', methods=['GET', 'POST'])
@manage_shows_required
def edit_show(show_id):
    show = Show.query.get_or_404(show_id)
    form = ShowForm(obj=show)

    if form.validate_on_submit():
        show.title = form.title.data.strip()
        show.description = form.description.data.strip() if form.description.data else None
        show.scheduling_mode = form.scheduling_mode.data
        show.allow_choice = form.allow_choice.data
        show.registration_open = form.registration_open.data
        show.registration_close = form.registration_close.data

        if form.scheduling_mode.data == 'block':
            show.max_per_block = form.max_per_block.data or 10
            show.block_duration_minutes = form.block_duration_minutes.data or 90
        else:
            show.slot_duration_minutes = int(form.slot_duration_minutes.data)

        custom_fields_json = request.form.get('custom_fields_json', '[]')
        try:
            show.custom_fields = json.loads(custom_fields_json)
        except (json.JSONDecodeError, TypeError):
            show.custom_fields = []

        roles_json = request.form.get('roles_json', '[]')
        try:
            show.roles = [r.strip() for r in json.loads(roles_json) if r.strip()]
        except (json.JSONDecodeError, TypeError):
            show.roles = []

        show.notify_email = form.notify_email.data.strip() if form.notify_email.data else None

        db.session.commit()
        flash(f'Show "{show.title}" updated.', 'success')
        return redirect(url_for('auditions.show_detail', show_id=show.id))

    if show.slot_duration_minutes:
        form.slot_duration_minutes.data = str(show.slot_duration_minutes)

    return render_template('auditions/admin/show_form.html', form=form, show=show, editing=True)


@auditions_bp.route('/admin/shows/<int:show_id>')
@read_admin_required
def show_detail(show_id):
    if not user_can_access_show(show_id):
        abort(403)
    show = Show.query.get_or_404(show_id)
    slots = AuditionSlot.query.filter_by(show_id=show.id).order_by(
        AuditionSlot.date, AuditionSlot.start_time
    ).all()

    # Filtering
    status_filter = request.args.get('status', '')
    tag_filter = request.args.get('tag', '')
    search = request.args.get('q', '').strip()

    reg_query = Registration.query.filter_by(show_id=show.id)

    if status_filter:
        reg_query = reg_query.filter(Registration.status == status_filter)
    else:
        reg_query = reg_query.filter(Registration.status != 'cancelled')

    if tag_filter:
        reg_query = reg_query.filter(Registration.tags.any(Tag.name == tag_filter))

    if search:
        reg_query = reg_query.join(Registration.user).filter(
            db.or_(
                User.first_name.ilike(f'%{search}%'),
                User.last_name.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%')
            )
        )

    registrations = reg_query.order_by(Registration.created_at.desc()).all()

    # All registrations (unfiltered) for stats
    all_regs = Registration.query.filter_by(show_id=show.id).all()

    # Group slots by date
    slots_by_date = {}
    for slot in slots:
        date_str = slot.date.strftime('%A, %B %d, %Y')
        if date_str not in slots_by_date:
            slots_by_date[date_str] = []
        slots_by_date[date_str].append(slot)

    # All tags for filter dropdown
    all_tags = Tag.query.order_by(Tag.name).all()

    # Unique sorted dates for the email-by-date filter
    slot_dates = sorted(set(s.date for s in slots))

    # Pre-compute email lists for Copy Emails modal (by date + status)
    # Key '' = all dates combined; date ISO string = that night only
    _email_buckets: dict = {'': {'all': [], 'confirmed': [], 'callback': [], 'waitlisted': []}}
    for _d in slot_dates:
        _email_buckets[_d.isoformat()] = {'all': [], 'confirmed': [], 'callback': [], 'waitlisted': []}
    for reg in all_regs:
        if reg.status == 'cancelled' or not reg.user.contact_email_ok:
            continue
        _email = reg.user.email
        _date_key = reg.slot.date.isoformat() if reg.slot else ''
        for _key in (['', _date_key] if _date_key else ['']):
            _email_buckets.setdefault(_key, {'all': [], 'confirmed': [], 'callback': [], 'waitlisted': []})
            _email_buckets[_key]['all'].append(_email)
            if reg.status in ('confirmed', 'callback', 'waitlisted'):
                _email_buckets[_key][reg.status].append(_email)
    copy_emails_json = json.dumps(_email_buckets)

    return render_template(
        'auditions/admin/show_detail.html',
        show=show,
        slots=slots,
        slots_by_date=slots_by_date,
        slot_dates=slot_dates,
        registrations=registrations,
        all_regs=all_regs,
        all_tags=all_tags,
        status_filter=status_filter,
        tag_filter=tag_filter,
        copy_emails_json=copy_emails_json,
        search=search,
        generate_form=GenerateSlotsForm()
    )


# ---------------------------------------------------------------------------
# Slot Management
# ---------------------------------------------------------------------------

@auditions_bp.route('/admin/shows/<int:show_id>/generate-slots', methods=['POST'])
@manage_shows_required
def generate_show_slots(show_id):
    show = Show.query.get_or_404(show_id)

    dates_json = request.form.get('audition_dates_json', '[]')
    try:
        audition_dates = json.loads(dates_json)
    except (json.JSONDecodeError, TypeError):
        flash('Invalid audition dates data.', 'danger')
        return redirect(url_for('auditions.show_detail', show_id=show.id))

    if not audition_dates:
        flash('Please add at least one audition date.', 'warning')
        return redirect(url_for('auditions.show_detail', show_id=show.id))

    for entry in audition_dates:
        if show.scheduling_mode == 'block':
            entry.setdefault('blocks_per_night', 2)
        else:
            entry.setdefault('total_hours', '3')

    existing_registrations = Registration.query.filter_by(
        show_id=show.id, status='confirmed'
    ).count()
    if existing_registrations > 0:
        flash('Cannot regenerate slots — there are confirmed registrations. Cancel them first.', 'danger')
        return redirect(url_for('auditions.show_detail', show_id=show.id))

    slots_created = generate_slots(show, audition_dates)
    show.audition_dates = audition_dates
    db.session.commit()

    flash(f'{slots_created} audition {"blocks" if show.scheduling_mode == "block" else "slots"} generated.', 'success')
    return redirect(url_for('auditions.show_detail', show_id=show.id))


@auditions_bp.route('/admin/shows/<int:show_id>/add-slots', methods=['POST'])
@manage_shows_required
def add_show_slots(show_id):
    show = Show.query.get_or_404(show_id)

    dates_json = request.form.get('add_dates_json', '[]')
    try:
        audition_dates = json.loads(dates_json)
    except (json.JSONDecodeError, TypeError):
        flash('Invalid audition dates data.', 'danger')
        return redirect(url_for('auditions.show_detail', show_id=show.id))

    if not audition_dates:
        flash('Please add at least one audition date.', 'warning')
        return redirect(url_for('auditions.show_detail', show_id=show.id))

    for entry in audition_dates:
        if show.scheduling_mode == 'block':
            entry.setdefault('blocks_per_night', 2)
        else:
            entry.setdefault('total_hours', '3')

    slots_created = add_slots(show, audition_dates)

    existing_dates = show.audition_dates or []
    show.audition_dates = existing_dates + audition_dates
    db.session.commit()

    flash(f'{slots_created} additional {"blocks" if show.scheduling_mode == "block" else "slots"} added.', 'success')
    return redirect(url_for('auditions.show_detail', show_id=show.id))


@auditions_bp.route('/admin/slots/<int:slot_id>/toggle-block', methods=['POST'])
@manage_shows_required
def toggle_slot_block(slot_id):
    """Block an open slot or unblock a reserved slot."""
    slot = AuditionSlot.query.get_or_404(slot_id)

    if slot.slot_type == 'reserved':
        # Unblock
        slot.slot_type = 'individual'
        db.session.commit()
        flash(f'Slot {slot.start_time.strftime("%I:%M %p")} on {slot.date.strftime("%b %d")} is now open.', 'success')
    else:
        # Block — only if no one is booked into it
        booked = slot.registrations.filter(
            Registration.status.in_(['confirmed', 'callback'])
        ).count()
        if booked:
            flash('Cannot block a slot that has confirmed registrations.', 'danger')
        else:
            slot.slot_type = 'reserved'
            db.session.commit()
            flash(f'Slot {slot.start_time.strftime("%I:%M %p")} on {slot.date.strftime("%b %d")} is now blocked.', 'success')

    return redirect(url_for('auditions.show_detail', show_id=slot.show_id))


@auditions_bp.route('/admin/slots/<int:slot_id>/edit-time', methods=['POST'])
@manage_shows_required
def edit_slot_time(slot_id):
    """Update the start and end time of a slot."""
    from datetime import time as time_type
    slot = AuditionSlot.query.get_or_404(slot_id)

    start_str = request.form.get('start_time', '').strip()
    end_str   = request.form.get('end_time', '').strip()

    try:
        slot.start_time = time_type.fromisoformat(start_str)
        slot.end_time   = time_type.fromisoformat(end_str)
    except ValueError:
        flash('Invalid time format.', 'danger')
        return redirect(url_for('auditions.show_detail', show_id=slot.show_id))

    if slot.end_time <= slot.start_time:
        flash('End time must be after start time.', 'danger')
        return redirect(url_for('auditions.show_detail', show_id=slot.show_id))

    db.session.commit()
    flash(
        f'Slot updated to {slot.start_time.strftime("%I:%M %p")} – {slot.end_time.strftime("%I:%M %p")} '
        f'on {slot.date.strftime("%b %d")}.',
        'success'
    )
    return redirect(url_for('auditions.show_detail', show_id=slot.show_id))


@auditions_bp.route('/admin/shows/<int:show_id>/status', methods=['POST'])
@manage_shows_required
def update_show_status(show_id):
    show = Show.query.get_or_404(show_id)
    new_status = request.form.get('status')
    if new_status in ('draft', 'open', 'closed', 'archived'):
        show.status = new_status
        db.session.commit()
        flash(f'Show status updated to {new_status}.', 'success')
    else:
        flash('Invalid status.', 'danger')
    return redirect(url_for('auditions.show_detail', show_id=show.id))


@auditions_bp.route('/admin/shows/<int:show_id>/delete', methods=['POST'])
@manage_shows_required
def delete_show(show_id):
    show = Show.query.get_or_404(show_id)
    title = show.title

    registrations = Registration.query.filter_by(show_id=show.id).count()
    if registrations > 0:
        flash('Cannot delete a show with existing registrations.', 'danger')
        return redirect(url_for('auditions.show_detail', show_id=show.id))

    db.session.delete(show)
    db.session.commit()
    flash(f'Show "{title}" deleted.', 'success')
    return redirect(url_for('auditions.admin_dashboard'))


# ---------------------------------------------------------------------------
# Registration Detail & Management
# ---------------------------------------------------------------------------

@auditions_bp.route('/admin/registrations/<int:reg_id>')
@read_admin_required
def registration_detail(reg_id):
    registration = Registration.query.get_or_404(reg_id)
    if not user_can_access_show(registration.show_id):
        abort(403)
    all_tags = Tag.query.order_by(Tag.name).all()
    reg_tag_ids = [t.id for t in registration.tags]

    # Slots for the change-slot modal (all non-reserved slots for this show)
    show_slots = AuditionSlot.query.filter_by(show_id=registration.show_id).filter(
        AuditionSlot.slot_type != 'reserved'
    ).order_by(AuditionSlot.date, AuditionSlot.start_time).all()

    slots_by_date = {}
    for slot in show_slots:
        date_str = slot.date.strftime('%A, %B %d, %Y')
        if date_str not in slots_by_date:
            slots_by_date[date_str] = []
        slots_by_date[date_str].append(slot)

    personal_note = RegistrationPersonalNote.query.filter_by(
        registration_id=registration.id,
        user_id=current_user.id
    ).first()

    return render_template(
        'auditions/admin/registration_detail.html',
        reg=registration,
        all_tags=all_tags,
        reg_tag_ids=reg_tag_ids,
        slots_by_date=slots_by_date,
        personal_note=personal_note,
    )


@auditions_bp.route('/admin/registrations/<int:reg_id>/save', methods=['POST'])
@evaluate_required
def save_registration_fields(reg_id):
    """Unified save: audition notes, admin notes, and tags."""
    registration = Registration.query.get_or_404(reg_id)
    if not user_can_access_show(registration.show_id):
        abort(403)

    registration.callback_for = request.form.get('callback_for', '').strip() or None
    registration.audition_notes = request.form.get('audition_notes', '').strip() or None
    registration.notes = request.form.get('notes', '').strip() or None

    tag_ids = [int(x) for x in request.form.getlist('tag_ids') if x.isdigit()]
    registration.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []

    db.session.commit()
    flash('Changes saved.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/registrations/<int:reg_id>/personal-note', methods=['POST'])
@read_admin_required
def save_personal_note(reg_id):
    """Save the current user's private note on a registration."""
    registration = Registration.query.get_or_404(reg_id)
    if not user_can_access_show(registration.show_id):
        abort(403)

    note_text = request.form.get('personal_note', '').strip() or None

    note = RegistrationPersonalNote.query.filter_by(
        registration_id=reg_id,
        user_id=current_user.id
    ).first()

    if note:
        note.note_text = note_text
        note.updated_at = datetime.utcnow()
    else:
        note = RegistrationPersonalNote(
            registration_id=reg_id,
            user_id=current_user.id,
            note_text=note_text,
        )
        db.session.add(note)

    db.session.commit()
    flash('Your note has been saved.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/registrations/files/<int:file_id>/delete', methods=['POST'])
@manage_shows_required
def delete_registration_file(file_id):
    """Delete an uploaded attachment from a registration."""
    reg_file = RegistrationFile.query.get_or_404(file_id)
    reg_id = reg_file.registration_id
    full_path = os.path.join(current_app.root_path, 'static', reg_file.file_path)
    if os.path.exists(full_path):
        os.remove(full_path)
    db.session.delete(reg_file)
    db.session.commit()
    flash('Attachment deleted.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/registrations/<int:reg_id>/change-slot', methods=['POST'])
@manage_shows_required
def admin_change_slot(reg_id):
    registration = Registration.query.get_or_404(reg_id)

    new_slot_id = request.form.get('slot_id')
    send_email = request.form.get('send_email') == '1'

    if not new_slot_id:
        flash('Please select a slot.', 'warning')
        return redirect(url_for('auditions.registration_detail', reg_id=reg_id))

    new_slot = AuditionSlot.query.get(int(new_slot_id))
    if not new_slot or new_slot.show_id != registration.show_id:
        flash('Invalid slot.', 'danger')
        return redirect(url_for('auditions.registration_detail', reg_id=reg_id))

    if new_slot.id == registration.slot_id:
        flash('That is already their current slot.', 'info')
        return redirect(url_for('auditions.registration_detail', reg_id=reg_id))

    # Free the old slot
    old_slot = registration.slot
    if old_slot:
        old_slot.current_count = max(0, old_slot.current_count - 1)

    # Assign the new slot
    registration.slot_id = new_slot.id
    registration.status = 'confirmed'
    new_slot.current_count += 1
    db.session.commit()

    if send_email:
        from auditions.email import send_slot_changed_email
        send_slot_changed_email(registration)

    flash(
        f'{registration.user.first_name} {registration.user.last_name} moved to '
        f'{new_slot.date.strftime("%b %d")} at {new_slot.start_time.strftime("%I:%M %p")}.',
        'success'
    )
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/registrations/<int:reg_id>/status', methods=['POST'])
@evaluate_required
def update_registration_status(reg_id):
    registration = Registration.query.get_or_404(reg_id)
    new_status = request.form.get('status')

    if new_status not in ('confirmed', 'waitlisted', 'callback', 'cancelled', 'no_show', 'not_selected'):
        flash('Invalid status.', 'danger')
        return redirect(url_for('auditions.registration_detail', reg_id=reg_id))

    old_status = registration.status
    show_id = registration.show_id

    # Only cancellations free the slot; no_show and not_selected keep it
    if new_status == 'cancelled' and old_status != 'cancelled':
        if registration.slot_id and registration.slot:
            registration.slot.current_count = max(0, registration.slot.current_count - 1)
        registration.slot_id = None

    registration.status = new_status
    db.session.commit()

    # When cancelling: notify actor and promote waitlist
    if new_status == 'cancelled' and old_status != 'cancelled':
        send_cancellation_email(registration)
        promote_from_waitlist(show_id)

    label = 'No Show' if new_status == 'no_show' else new_status.capitalize()
    flash(f'Registration status updated to {label}.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/shows/<int:show_id>/bulk-status', methods=['POST'])
@evaluate_required
def bulk_update_status(show_id):
    """Bulk-update the status of multiple registrations at once."""
    if not user_can_access_show(show_id):
        abort(403)

    new_status = request.form.get('status')
    if new_status not in ('confirmed', 'waitlisted', 'callback', 'cancelled', 'no_show', 'not_selected'):
        flash('Invalid status.', 'danger')
        return redirect(url_for('auditions.show_detail', show_id=show_id))

    reg_ids = [int(x) for x in request.form.getlist('reg_ids') if x.isdigit()]
    if not reg_ids:
        flash('No registrations selected.', 'warning')
        return redirect(url_for('auditions.show_detail', show_id=show_id))

    registrations = Registration.query.filter(
        Registration.id.in_(reg_ids),
        Registration.show_id == show_id
    ).all()

    for registration in registrations:
        old_status = registration.status
        if old_status == new_status:
            continue

        # Only cancellations free the slot; no_show and not_selected keep it
        if new_status == 'cancelled' and old_status != 'cancelled':
            if registration.slot_id and registration.slot:
                registration.slot.current_count = max(0, registration.slot.current_count - 1)
            registration.slot_id = None

        registration.status = new_status

        if new_status == 'cancelled' and old_status != 'cancelled':
            send_cancellation_email(registration)

    db.session.commit()

    # Promote from waitlist once after all cancellations are processed
    if new_status == 'cancelled':
        promote_from_waitlist(show_id)

    label = 'No Show' if new_status == 'no_show' else new_status.capitalize()
    flash(f'{len(registrations)} registration(s) updated to {label}.', 'success')
    return redirect(url_for('auditions.show_detail', show_id=show_id))


@auditions_bp.route('/admin/registrations/<int:reg_id>/notes', methods=['POST'])
@evaluate_required
def update_registration_notes(reg_id):
    registration = Registration.query.get_or_404(reg_id)
    registration.notes = request.form.get('notes', '').strip() or None
    db.session.commit()
    flash('Notes saved.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/registrations/<int:reg_id>/audition-notes', methods=['POST'])
@evaluate_required
def update_audition_notes(reg_id):
    registration = Registration.query.get_or_404(reg_id)
    registration.audition_notes = request.form.get('audition_notes', '').strip() or None
    db.session.commit()
    flash('Audition notes saved.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/registrations/<int:reg_id>/upload-photo', methods=['POST'])
@evaluate_required
def upload_headshot(reg_id):
    """Upload or replace a headshot photo for a registration."""
    import os
    from werkzeug.utils import secure_filename
    from flask import current_app

    registration = Registration.query.get_or_404(reg_id)

    photo = request.files.get('headshot')
    if not photo or not photo.filename:
        flash('No file selected.', 'warning')
        return redirect(url_for('auditions.registration_detail', reg_id=reg_id))

    allowed = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    ext = photo.filename.rsplit('.', 1)[-1].lower() if '.' in photo.filename else ''
    if ext not in allowed:
        flash('Only JPG, PNG, GIF, or WEBP images are allowed.', 'danger')
        return redirect(url_for('auditions.registration_detail', reg_id=reg_id))

    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'headshots')
    os.makedirs(upload_dir, exist_ok=True)

    # Delete old file if present
    if registration.headshot_path:
        old_path = os.path.join(current_app.root_path, 'static', registration.headshot_path)
        if os.path.exists(old_path):
            os.remove(old_path)

    filename = secure_filename(f'reg_{reg_id}_{registration.user.last_name}_{registration.user.first_name}.{ext}')
    photo.save(os.path.join(upload_dir, filename))
    registration.headshot_path = f'auditions/uploads/headshots/{filename}'
    db.session.commit()

    flash('Photo saved.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/registrations/<int:reg_id>/tags', methods=['POST'])
@evaluate_required
def update_registration_tags(reg_id):
    registration = Registration.query.get_or_404(reg_id)

    # Get submitted tag IDs
    tag_ids = request.form.getlist('tag_ids', type=int)
    tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
    registration.tags = tags
    db.session.commit()

    flash('Tags updated.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/tags/create', methods=['POST'])
@evaluate_required
def create_tag():
    """Create a new tag via AJAX or form submit."""
    name = request.form.get('name', '').strip().lower()
    if not name:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Tag name required'}), 400
        flash('Tag name is required.', 'danger')
        return redirect(request.referrer or url_for('auditions.admin_dashboard'))

    tag = Tag.query.filter_by(name=name).first()
    if not tag:
        tag = Tag(name=name)
        db.session.add(tag)
        db.session.commit()

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'id': tag.id, 'name': tag.name})

    flash(f'Tag "{name}" created.', 'success')
    return redirect(request.referrer or url_for('auditions.admin_dashboard'))


# ---------------------------------------------------------------------------
# Admin: Register an Actor for a Show
# ---------------------------------------------------------------------------

@auditions_bp.route('/admin/shows/<int:show_id>/register', methods=['GET', 'POST'])
@manage_shows_required
def admin_register_actor(show_id):
    """Admin-side registration: find/create an actor and register them for a show."""
    show = Show.query.get_or_404(show_id)

    # All slots grouped by date (admin sees every slot, including full ones)
    slots = AuditionSlot.query.filter_by(show_id=show.id).filter(
        AuditionSlot.slot_type != 'reserved'
    ).order_by(AuditionSlot.date, AuditionSlot.start_time).all()

    slots_by_date = {}
    for slot in slots:
        date_str = slot.date.strftime('%A, %B %d, %Y')
        if date_str not in slots_by_date:
            slots_by_date[date_str] = []
        slots_by_date[date_str].append(slot)

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip() or None
        send_email = request.form.get('send_email') == '1'

        if not email or not first_name or not last_name:
            flash('Email, first name, and last name are required.', 'danger')
            return redirect(url_for('auditions.admin_register_actor', show_id=show.id))

        # Find or create actor account
        import secrets
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                role='actor'
            )
            # Set a random password — they can use "forgot password" to set their own
            user.set_password(secrets.token_urlsafe(16))
            db.session.add(user)
            db.session.flush()  # get user.id before commit
        else:
            # Update name/phone if admin changed them
            user.first_name = first_name
            user.last_name = last_name
            if phone:
                user.phone = phone

        # Check for duplicate registration
        existing = Registration.query.filter_by(
            user_id=user.id, show_id=show.id
        ).filter(Registration.status != 'cancelled').first()
        if existing:
            flash(f'{first_name} {last_name} already has an active registration for this show.', 'warning')
            return redirect(url_for('auditions.show_detail', show_id=show.id))

        # Build registration
        registration = Registration(
            user_id=user.id,
            show_id=show.id
        )

        registration.roles_auditioning_for = request.form.get('roles_auditioning_for', '').strip() or None
        registration.accept_other_role = request.form.get('accept_other_role') == 'yes'
        registration.schedule_conflicts = request.form.get('schedule_conflicts', '').strip() or None
        registration.video_link = request.form.get('video_link', '').strip() or None

        if show.custom_fields:
            custom_data = {}
            for field in show.custom_fields:
                key = f'custom_{field["name"]}'
                if field['type'] == 'checkbox':
                    custom_data[field['name']] = 'yes' if request.form.get(key) else 'no'
                else:
                    custom_data[field['name']] = request.form.get(key, '').strip()
            registration.custom_field_data = custom_data

        # Slot assignment
        chosen_slot_id = request.form.get('slot_id')
        if chosen_slot_id:
            slot = AuditionSlot.query.get(int(chosen_slot_id))
            if slot and slot.show_id == show.id and slot.slot_type != 'reserved':
                registration.slot_id = slot.id
                registration.status = 'confirmed'
                slot.current_count += 1
            else:
                flash('Invalid slot selected.', 'danger')
                return redirect(url_for('auditions.admin_register_actor', show_id=show.id))
        else:
            registration.status = 'waitlisted'

        db.session.add(registration)
        db.session.commit()

        if send_email:
            if registration.status == 'confirmed':
                send_confirmation_email(registration)
            else:
                send_waitlist_email(registration)

        send_admin_notification(registration, 'New Registration (Admin)')

        flash(
            f'{first_name} {last_name} registered as '
            f'{"confirmed" if registration.status == "confirmed" else "waitlisted"}.',
            'success'
        )
        return redirect(url_for('auditions.show_detail', show_id=show.id))

    return render_template(
        'auditions/admin/register_actor.html',
        show=show,
        slots=slots,
        slots_by_date=slots_by_date,
    )


@auditions_bp.route('/admin/admins/add', methods=['POST'])
@manage_shows_required
def add_staff_member():
    """Super admin: create a new staff user account."""
    if not current_user.is_super_admin:
        abort(403)

    valid_roles = ('super_admin', 'auditions_creator', 'director', 'producer',
                   'stage_manager', 'no_rights')

    email = request.form.get('email', '').lower().strip()
    first_name = request.form.get('first_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    role = request.form.get('role', '').strip()

    if not all([email, first_name, last_name, role]):
        flash('All fields are required.', 'danger')
        return redirect(url_for('auditions.admin_dashboard'))

    if role not in valid_roles:
        flash('Invalid role selected.', 'danger')
        return redirect(url_for('auditions.admin_dashboard'))

    role_labels = {
        'super_admin': 'Super Admin', 'auditions_creator': 'Auditions Creator',
        'director': 'Director', 'producer': 'Producer',
        'stage_manager': 'Stage Manager', 'no_rights': 'No Rights',
    }

    existing = User.query.filter_by(email=email).first()
    if existing:
        # Promote the existing account to the chosen role
        existing.role = role
        db.session.commit()
        flash(
            f'{existing.first_name} {existing.last_name} already had an account — '
            f'their role has been updated to {role_labels.get(role, role)}.',
            'success'
        )
        return redirect(url_for('auditions.admin_dashboard'))

    if not all([first_name, last_name]):
        flash('First name and last name are required for new accounts.', 'danger')
        return redirect(url_for('auditions.admin_dashboard'))

    user = User(
        email=email,
        first_name=first_name,
        last_name=last_name,
        role=role,
    )
    db.session.add(user)
    db.session.commit()

    flash(
        f'{first_name} {last_name} added as {role_labels.get(role, role)}. '
        f'They can now sign in with Google at {email}.',
        'success'
    )
    return redirect(url_for('auditions.admin_dashboard'))


@auditions_bp.route('/admin/admins/update-all', methods=['POST'])
@manage_shows_required
def update_all_staff():
    """Super admin: save role and show access for all staff in one submission."""
    if not current_user.is_super_admin:
        abort(403)

    valid_roles = ('super_admin', 'auditions_creator', 'director', 'producer',
                   'stage_manager', 'no_rights')
    staff_roles = ('super_admin', 'admin', 'auditions_creator', 'director',
                   'producer', 'stage_manager', 'viewer', 'no_rights')
    staff_users = User.query.filter(
        User.role.in_(staff_roles),
        User.id != current_user.id
    ).all()

    changes = []
    for user in staff_users:
        new_role = request.form.get(f'role_{user.id}', '').strip()
        if new_role not in valid_roles:
            continue

        old_role = user.role_display
        user.role = new_role

        show_ids = request.form.getlist(f'show_ids_{user.id}', type=int)
        user.managed_shows = show_ids if show_ids else None

        if old_role != user.role_display:
            changes.append(f'{user.first_name} {user.last_name} → {user.role_display}')

    db.session.commit()

    if changes:
        flash('Changes saved. Role updates: ' + '; '.join(changes), 'success')
    else:
        flash('Changes saved.', 'success')
    return redirect(url_for('auditions.admin_dashboard'))


@auditions_bp.route('/admin/actors/lookup')
@manage_shows_required
def lookup_actor():
    """AJAX: look up an actor by email and return their profile fields as JSON."""
    email = request.args.get('email', '').strip().lower()
    if not email:
        return jsonify({})
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'found': False})
    return jsonify({
        'found': True,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'phone': user.phone or '',
    })


# ---------------------------------------------------------------------------
# Actor Profile Editing (admin)
# ---------------------------------------------------------------------------

VOLUNTEER_INTEREST_FIELDS = [
    'choreographer', 'concession', 'costume_design', 'director',
    'lighting_design', 'lighting_operator', 'music_director', 'photography',
    'producer', 'props_master', 'set_build', 'set_design', 'set_dressing',
    'set_painting', 'sound_design', 'sound_operator', 'stagehand',
    'stage_manager', 'usher',
]


@auditions_bp.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@manage_shows_required
def edit_actor(user_id):
    user = User.query.get_or_404(user_id)
    back = request.args.get('back') or request.form.get('back', '')

    if request.method == 'POST':
        user.first_name = request.form.get('first_name', '').strip() or user.first_name
        user.last_name = request.form.get('last_name', '').strip() or user.last_name
        user.phone = request.form.get('phone', '').strip() or None
        user.address = request.form.get('address', '').strip() or None
        user.city = request.form.get('city', '').strip() or None
        user.province = request.form.get('province', '').strip() or None
        user.postal_code = request.form.get('postal_code', '').strip() or None
        user.pronouns = request.form.get('pronouns', '').strip() or None
        user.contact_email_ok = (request.form.get('contact_email_ok') == 'yes')
        past_raw = request.form.get('past_member')
        user.past_member = True if past_raw == 'yes' else (False if past_raw == 'no' else None)
        user.hear_about_us = request.form.get('hear_about_us', '').strip() or None

        # Profile fields
        comfortable = request.form.get('comfortable_performing')
        if comfortable in ('yes', 'no'):
            user.comfortable_performing = (comfortable == 'yes')
        equity = request.form.get('equity_or_actra')
        if equity in ('yes', 'no'):
            user.equity_or_actra = (equity == 'yes')
        user.training = request.form.get('training', '').strip() or None

        # Acting experience JSON
        try:
            user.acting_experience = json.loads(request.form.get('acting_experience_json', '[]'))
        except (json.JSONDecodeError, TypeError):
            pass

        # Volunteer interests
        user.volunteer_interests = [
            key for key in VOLUNTEER_INTEREST_FIELDS
            if request.form.get(f'interest_{key}')
        ]

        db.session.commit()
        flash('Profile updated.', 'success')

        if back:
            return redirect(url_for('auditions.registration_detail', reg_id=int(back)))
        return redirect(url_for('auditions.edit_actor', user_id=user.id))

    acting_experience_json = json.dumps(user.acting_experience or [])
    volunteer_set = set(user.volunteer_interests or [])
    return render_template(
        'auditions/admin/edit_actor.html',
        user=user,
        back=back,
        acting_experience_json=acting_experience_json,
        volunteer_set=volunteer_set,
        volunteer_fields=VOLUNTEER_INTEREST_FIELDS,
    )


# ---------------------------------------------------------------------------
# Email Actions from Admin
# ---------------------------------------------------------------------------

@auditions_bp.route('/admin/registrations/<int:reg_id>/send-callback', methods=['POST'])
@evaluate_required
def send_callback(reg_id):
    registration = Registration.query.get_or_404(reg_id)
    callback_details = request.form.get('callback_details', '').strip()

    # Mark as callback
    registration.status = 'callback'
    db.session.commit()

    send_callback_email(registration, callback_details=callback_details)
    flash(f'Callback email sent to {registration.user.email}.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/registrations/<int:reg_id>/request-materials', methods=['POST'])
@evaluate_required
def request_materials(reg_id):
    registration = Registration.query.get_or_404(reg_id)
    items = request.form.getlist('items')
    if not items:
        flash('Please select at least one item to request.', 'warning')
        return redirect(url_for('auditions.registration_detail', reg_id=reg_id))

    send_info_request_email(registration, requested_items=items)
    flash(f'Materials request sent to {registration.user.email}.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/registrations/<int:reg_id>/resend-confirmation', methods=['POST'])
@manage_shows_required
def resend_confirmation(reg_id):
    registration = Registration.query.get_or_404(reg_id)
    send_confirmation_email(registration)
    flash(f'Confirmation email resent to {registration.user.email}.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/shows/<int:show_id>/email-all', methods=['POST'])
@evaluate_required
def email_all_auditioners(show_id):
    """Send a custom email to all (or filtered) auditioners for a show."""
    from auditions.email import send_bulk_email
    show = Show.query.get_or_404(show_id)
    if not user_can_access_show(show_id):
        abort(403)

    subject    = request.form.get('subject', '').strip()
    body       = request.form.get('body', '').strip()
    statuses   = request.form.getlist('statuses')
    slot_date_str = request.form.get('slot_date', '').strip()  # YYYY-MM-DD or ''

    if not subject or not body:
        flash('Subject and message are required.', 'danger')
        return redirect(url_for('auditions.show_detail', show_id=show_id))

    if not statuses:
        statuses = ['confirmed', 'callback', 'waitlisted']

    registrations = Registration.query.filter_by(show_id=show.id).filter(
        Registration.status.in_(statuses)
    ).all()

    # Optional: filter to a single audition date
    if slot_date_str:
        from datetime import date as date_cls
        try:
            filter_date = date_cls.fromisoformat(slot_date_str)
            registrations = [r for r in registrations if r.slot and r.slot.date == filter_date]
        except ValueError:
            pass

    if not registrations:
        flash('No matching registrations to email.', 'warning')
        return redirect(url_for('auditions.show_detail', show_id=show_id))

    sent, failed = send_bulk_email(show, registrations, subject, body)

    if failed:
        flash(f'Sent to {sent} auditioner(s). {failed} failed — check server logs.', 'warning')
    else:
        flash(f'Email sent successfully to {sent} auditioner(s).', 'success')
    return redirect(url_for('auditions.show_detail', show_id=show_id))
