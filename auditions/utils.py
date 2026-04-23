from datetime import datetime, timedelta, date as date_type, time as time_type
from auditions.models import db, AuditionSlot, Registration, Show


def generate_slots(show, audition_dates):
    """
    Generate audition slots/blocks for a show based on its scheduling mode.

    Args:
        show: Show model instance
        audition_dates: List of dicts with 'date' (YYYY-MM-DD) and 'start_time' (HH:MM)

    Returns:
        Number of slots created
    """
    # Clear any existing slots for this show
    AuditionSlot.query.filter_by(show_id=show.id).delete()

    slots_created = 0

    for entry in audition_dates:
        slot_date = datetime.strptime(entry['date'], '%Y-%m-%d').date()
        start = datetime.strptime(entry['start_time'], '%H:%M')

        if show.scheduling_mode == 'block':
            blocks_per_night = entry.get('blocks_per_night', 2)
            for i in range(blocks_per_night):
                block_start = start + timedelta(minutes=show.block_duration_minutes * i)
                block_end = block_start + timedelta(minutes=show.block_duration_minutes)

                slot = AuditionSlot(
                    show_id=show.id,
                    date=slot_date,
                    start_time=block_start.time(),
                    end_time=block_end.time(),
                    capacity=show.max_per_block,
                    current_count=0
                )
                db.session.add(slot)
                slots_created += 1

        elif show.scheduling_mode == 'slot':
            total_minutes = float(entry.get('total_hours', 3)) * 60
            duration = show.slot_duration_minutes
            num_slots = int(total_minutes // duration)

            for i in range(num_slots):
                slot_start = start + timedelta(minutes=duration * i)
                slot_end = slot_start + timedelta(minutes=duration)

                slot = AuditionSlot(
                    show_id=show.id,
                    date=slot_date,
                    start_time=slot_start.time(),
                    end_time=slot_end.time(),
                    capacity=1,
                    current_count=0
                )
                db.session.add(slot)
                slots_created += 1

    db.session.commit()
    return slots_created


def add_slots(show, audition_dates):
    """
    Add additional slots/blocks to a show WITHOUT deleting existing ones.

    Args:
        show: Show model instance
        audition_dates: List of dicts with 'date' (YYYY-MM-DD) and 'start_time' (HH:MM)

    Returns:
        Number of slots created
    """
    slots_created = 0

    for entry in audition_dates:
        slot_date = datetime.strptime(entry['date'], '%Y-%m-%d').date()
        start = datetime.strptime(entry['start_time'], '%H:%M')

        if show.scheduling_mode == 'block':
            blocks_per_night = entry.get('blocks_per_night', 2)
            for i in range(blocks_per_night):
                block_start = start + timedelta(minutes=show.block_duration_minutes * i)
                block_end = block_start + timedelta(minutes=show.block_duration_minutes)

                slot = AuditionSlot(
                    show_id=show.id,
                    date=slot_date,
                    start_time=block_start.time(),
                    end_time=block_end.time(),
                    capacity=show.max_per_block,
                    current_count=0
                )
                db.session.add(slot)
                slots_created += 1

        elif show.scheduling_mode == 'slot':
            total_minutes = float(entry.get('total_hours', 3)) * 60
            duration = show.slot_duration_minutes
            num_slots = int(total_minutes // duration)

            for i in range(num_slots):
                slot_start = start + timedelta(minutes=duration * i)
                slot_end = slot_start + timedelta(minutes=duration)

                slot = AuditionSlot(
                    show_id=show.id,
                    date=slot_date,
                    start_time=slot_start.time(),
                    end_time=slot_end.time(),
                    capacity=1,
                    current_count=0
                )
                db.session.add(slot)
                slots_created += 1

    db.session.commit()
    return slots_created


def assign_slot(show, registration):
    """
    Auto-assign an actor to the first available slot for a show.
    If no slots are available, set status to waitlisted.

    Args:
        show: Show model instance
        registration: Registration model instance

    Returns:
        The updated registration
    """
    available = AuditionSlot.query.filter_by(show_id=show.id).filter(
        AuditionSlot.current_count < AuditionSlot.capacity
    ).order_by(AuditionSlot.date, AuditionSlot.start_time).first()

    if available:
        registration.slot_id = available.id
        registration.status = 'confirmed'
        available.current_count += 1
    else:
        registration.status = 'waitlisted'

    return registration


def promote_from_waitlist(show_id):
    """
    When a registration is cancelled, promote the oldest waitlisted
    registration for that show to a confirmed slot.

    Returns:
        The promoted registration, or None if no one to promote.
    """
    waitlisted = Registration.query.filter_by(
        show_id=show_id, status='waitlisted'
    ).order_by(Registration.created_at).first()

    if not waitlisted:
        return None

    show = Show.query.get(show_id)
    assign_slot(show, waitlisted)
    db.session.commit()
    return waitlisted
