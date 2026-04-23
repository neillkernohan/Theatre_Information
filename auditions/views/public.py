from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from auditions import auditions_bp
from auditions.models import db, Show, AuditionSlot, Registration
from auditions.utils import assign_slot, promote_from_waitlist
from auditions.email import send_confirmation_email, send_waitlist_email, send_cancellation_email
from auditions.views.auth import _save_profile_from_form, _prepopulate_profile_form
from auditions.forms import ActorProfileForm
from datetime import datetime
import json


@auditions_bp.route('/')
def index():
    now = datetime.utcnow()
    shows = Show.query.filter(
        Show.status == 'open',
        Show.registration_open <= now,
        Show.registration_close >= now
    ).order_by(Show.registration_close.asc()).all()
    return render_template('auditions/index.html', shows=shows)


@auditions_bp.route('/shows')
def shows_list():
    now = datetime.utcnow()
    shows = Show.query.filter(
        Show.status == 'open',
        Show.registration_open <= now,
        Show.registration_close >= now
    ).order_by(Show.registration_close.asc()).all()
    return render_template('auditions/public/shows.html', shows=shows)


@auditions_bp.route('/shows/<int:show_id>/register', methods=['GET', 'POST'])
@login_required
def register_for_show(show_id):
    show = Show.query.get_or_404(show_id)

    # Check show is open for registration
    now = datetime.utcnow()
    if show.status != 'open' or now < show.registration_open or now > show.registration_close:
        flash('Registration is not currently open for this show.', 'warning')
        return redirect(url_for('auditions.shows_list'))

    # Check if already registered
    existing = Registration.query.filter_by(
        user_id=current_user.id, show_id=show.id
    ).filter(Registration.status != 'cancelled').first()
    if existing:
        flash('You are already registered for this show.', 'info')
        return redirect(url_for('auditions.actor_dashboard'))

    # Get available slots
    available_slots = AuditionSlot.query.filter_by(show_id=show.id).filter(
        AuditionSlot.current_count < AuditionSlot.capacity
    ).order_by(AuditionSlot.date, AuditionSlot.start_time).all()

    # Group available slots by date for the template
    slots_by_date = {}
    for slot in available_slots:
        date_str = slot.date.strftime('%A, %B %d, %Y')
        if date_str not in slots_by_date:
            slots_by_date[date_str] = []
        slots_by_date[date_str].append(slot)

    profile_form = ActorProfileForm()

    if request.method == 'POST':
        # Save profile fields back to the user's permanent profile
        _save_profile_from_form(profile_form, current_user)

        # Create the registration
        registration = Registration(
            user_id=current_user.id,
            show_id=show.id
        )

        # Handle custom field data
        if show.custom_fields:
            custom_data = {}
            for field in show.custom_fields:
                field_name = f"custom_{field['name']}"
                custom_data[field['name']] = request.form.get(field_name, '')
            registration.custom_field_data = custom_data

        # Handle file uploads (headshot, resume) and video link
        registration.video_link = request.form.get('video_link', '').strip() or None

        # Slot assignment
        if show.allow_choice:
            # Actor chose a slot
            chosen_slot_id = request.form.get('slot_id')
            if chosen_slot_id:
                slot = AuditionSlot.query.get(int(chosen_slot_id))
                if slot and not slot.is_full and slot.show_id == show.id:
                    registration.slot_id = slot.id
                    registration.status = 'confirmed'
                    slot.current_count += 1
                else:
                    flash('That time slot is no longer available. Please choose another.', 'warning')
                    return redirect(url_for('auditions.register_for_show', show_id=show.id))
            else:
                # No slot chosen — waitlist
                registration.status = 'waitlisted'
        else:
            # Auto-assign
            assign_slot(show, registration)

        db.session.add(registration)
        db.session.commit()

        # Send confirmation or waitlist email
        if registration.status == 'confirmed':
            send_confirmation_email(registration)
            flash(f'You are confirmed for {show.title}! A confirmation email has been sent.', 'success')
        else:
            send_waitlist_email(registration)
            flash(f'All slots are full. You have been added to the waiting list for {show.title}. A confirmation email has been sent.', 'info')

        return redirect(url_for('auditions.actor_dashboard'))

    # Pre-populate profile form from user's saved profile
    _prepopulate_profile_form(profile_form, current_user)

    return render_template(
        'auditions/public/register_audition.html',
        show=show,
        slots_by_date=slots_by_date,
        available_slots=available_slots,
        profile_form=profile_form,
        acting_experience_json=json.dumps(current_user.acting_experience or [])
    )


@auditions_bp.route('/registrations/<int:reg_id>/cancel', methods=['POST'])
@login_required
def cancel_registration(reg_id):
    registration = Registration.query.get_or_404(reg_id)

    # Only the owner can cancel
    if registration.user_id != current_user.id:
        flash('You do not have permission to cancel this registration.', 'danger')
        return redirect(url_for('auditions.actor_dashboard'))

    if registration.status == 'cancelled':
        flash('This registration is already cancelled.', 'info')
        return redirect(url_for('auditions.actor_dashboard'))

    # Free up the slot
    if registration.slot_id and registration.slot:
        registration.slot.current_count = max(0, registration.slot.current_count - 1)

    show_id = registration.show_id
    registration.status = 'cancelled'
    registration.slot_id = None
    db.session.commit()

    # Send cancellation email
    send_cancellation_email(registration)

    # Promote from waitlist
    promote_from_waitlist(show_id)

    flash('Your registration has been cancelled. A confirmation email has been sent.', 'info')
    return redirect(url_for('auditions.actor_dashboard'))
