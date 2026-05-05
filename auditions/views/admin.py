from flask import render_template, abort, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from auditions import auditions_bp
from auditions.models import db, Show, AuditionSlot, Registration, Tag, User
from auditions.forms import ShowForm, GenerateSlotsForm
from auditions.utils import generate_slots, add_slots, promote_from_waitlist
from auditions.email import (
    send_callback_email, send_info_request_email,
    send_confirmation_email, send_cancellation_email, send_admin_notification
)
from auth.decorators import admin_required, viewer_required
import json


# ---------------------------------------------------------------------------
# Dashboard & Show Management
# ---------------------------------------------------------------------------

@auditions_bp.route('/admin/dashboard')
@viewer_required
def admin_dashboard():
    shows = Show.query.order_by(Show.created_at.desc()).all()
    return render_template('auditions/admin/dashboard.html', shows=shows)


@auditions_bp.route('/admin/shows/new', methods=['GET', 'POST'])
@admin_required
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

        show.notify_email = form.notify_email.data.strip() if form.notify_email.data else None

        db.session.add(show)
        db.session.commit()
        flash(f'Show "{show.title}" created. Now add audition dates and generate slots.', 'success')
        return redirect(url_for('auditions.show_detail', show_id=show.id))

    return render_template('auditions/admin/show_form.html', form=form, editing=False)


@auditions_bp.route('/admin/shows/<int:show_id>/edit', methods=['GET', 'POST'])
@admin_required
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

        show.notify_email = form.notify_email.data.strip() if form.notify_email.data else None

        db.session.commit()
        flash(f'Show "{show.title}" updated.', 'success')
        return redirect(url_for('auditions.show_detail', show_id=show.id))

    if show.slot_duration_minutes:
        form.slot_duration_minutes.data = str(show.slot_duration_minutes)

    return render_template('auditions/admin/show_form.html', form=form, show=show, editing=True)


@auditions_bp.route('/admin/shows/<int:show_id>')
@viewer_required
def show_detail(show_id):
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

    return render_template(
        'auditions/admin/show_detail.html',
        show=show,
        slots=slots,
        slots_by_date=slots_by_date,
        registrations=registrations,
        all_regs=all_regs,
        all_tags=all_tags,
        status_filter=status_filter,
        tag_filter=tag_filter,
        search=search,
        generate_form=GenerateSlotsForm()
    )


# ---------------------------------------------------------------------------
# Slot Management
# ---------------------------------------------------------------------------

@auditions_bp.route('/admin/shows/<int:show_id>/generate-slots', methods=['POST'])
@admin_required
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
@admin_required
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


@auditions_bp.route('/admin/shows/<int:show_id>/status', methods=['POST'])
@admin_required
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
@admin_required
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
@viewer_required
def registration_detail(reg_id):
    registration = Registration.query.get_or_404(reg_id)
    all_tags = Tag.query.order_by(Tag.name).all()
    reg_tag_ids = [t.id for t in registration.tags]
    return render_template(
        'auditions/admin/registration_detail.html',
        reg=registration,
        all_tags=all_tags,
        reg_tag_ids=reg_tag_ids
    )


@auditions_bp.route('/admin/registrations/<int:reg_id>/status', methods=['POST'])
@admin_required
def update_registration_status(reg_id):
    registration = Registration.query.get_or_404(reg_id)
    new_status = request.form.get('status')

    if new_status not in ('confirmed', 'waitlisted', 'callback', 'cancelled'):
        flash('Invalid status.', 'danger')
        return redirect(url_for('auditions.registration_detail', reg_id=reg_id))

    old_status = registration.status
    show_id = registration.show_id

    # Free slot if cancelling
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

    send_admin_notification(registration, f'Status Changed to {new_status.capitalize()}')

    flash(f'Registration status updated to {new_status}.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/registrations/<int:reg_id>/notes', methods=['POST'])
@admin_required
def update_registration_notes(reg_id):
    registration = Registration.query.get_or_404(reg_id)
    registration.notes = request.form.get('notes', '').strip() or None
    db.session.commit()
    flash('Notes saved.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))


@auditions_bp.route('/admin/registrations/<int:reg_id>/tags', methods=['POST'])
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
def resend_confirmation(reg_id):
    registration = Registration.query.get_or_404(reg_id)
    send_confirmation_email(registration)
    flash(f'Confirmation email resent to {registration.user.email}.', 'success')
    return redirect(url_for('auditions.registration_detail', reg_id=reg_id))
