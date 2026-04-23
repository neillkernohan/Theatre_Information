"""Tests for scheduling utilities: generate_slots, assign_slot, promote_from_waitlist."""
import pytest
from datetime import date, time


class TestGenerateSlots:

    def test_slot_mode_creates_correct_count(self, db, slot_show):
        from auditions.utils import generate_slots
        from auditions.models import AuditionSlot
        dates = [{'date': '2026-06-01', 'start_time': '19:00', 'total_hours': '1'}]
        count = generate_slots(slot_show, dates)
        assert count == 4  # 60 min / 15 min = 4 slots
        assert AuditionSlot.query.filter_by(show_id=slot_show.id).count() == 4

    def test_slot_mode_times_are_correct(self, db, slot_show):
        from auditions.utils import generate_slots
        from auditions.models import AuditionSlot
        dates = [{'date': '2026-06-01', 'start_time': '19:00', 'total_hours': '0.5'}]
        generate_slots(slot_show, dates)
        slots = AuditionSlot.query.filter_by(show_id=slot_show.id).order_by(
            AuditionSlot.start_time).all()
        assert slots[0].start_time == time(19, 0)
        assert slots[0].end_time == time(19, 15)
        assert slots[1].start_time == time(19, 15)
        assert slots[1].end_time == time(19, 30)

    def test_slot_mode_capacity_is_one(self, db, slot_show):
        from auditions.utils import generate_slots
        from auditions.models import AuditionSlot
        dates = [{'date': '2026-06-01', 'start_time': '19:00', 'total_hours': '0.25'}]
        generate_slots(slot_show, dates)
        slot = AuditionSlot.query.filter_by(show_id=slot_show.id).first()
        assert slot.capacity == 1

    def test_block_mode_creates_correct_count(self, db, block_show):
        from auditions.utils import generate_slots
        from auditions.models import AuditionSlot
        dates = [{'date': '2026-06-01', 'start_time': '18:00', 'blocks_per_night': 3}]
        count = generate_slots(block_show, dates)
        assert count == 3
        assert AuditionSlot.query.filter_by(show_id=block_show.id).count() == 3

    def test_block_mode_capacity_equals_max_per_block(self, db, block_show):
        from auditions.utils import generate_slots
        from auditions.models import AuditionSlot
        dates = [{'date': '2026-06-01', 'start_time': '18:00', 'blocks_per_night': 1}]
        generate_slots(block_show, dates)
        slot = AuditionSlot.query.filter_by(show_id=block_show.id).first()
        assert slot.capacity == block_show.max_per_block  # 5

    def test_regenerate_clears_existing_slots(self, db, slot_show):
        from auditions.utils import generate_slots
        from auditions.models import AuditionSlot
        dates = [{'date': '2026-06-01', 'start_time': '19:00', 'total_hours': '1'}]
        generate_slots(slot_show, dates)
        first_count = AuditionSlot.query.filter_by(show_id=slot_show.id).count()
        # Regenerate with different dates — old slots should be gone
        dates2 = [{'date': '2026-06-02', 'start_time': '19:00', 'total_hours': '0.5'}]
        generate_slots(slot_show, dates2)
        assert AuditionSlot.query.filter_by(
            show_id=slot_show.id, date=date(2026, 6, 1)
        ).count() == 0
        assert AuditionSlot.query.filter_by(
            show_id=slot_show.id, date=date(2026, 6, 2)
        ).count() == 2

    def test_multiple_dates(self, db, slot_show):
        from auditions.utils import generate_slots
        from auditions.models import AuditionSlot
        dates = [
            {'date': '2026-06-01', 'start_time': '19:00', 'total_hours': '0.5'},
            {'date': '2026-06-02', 'start_time': '19:00', 'total_hours': '0.5'},
        ]
        count = generate_slots(slot_show, dates)
        assert count == 4
        assert AuditionSlot.query.filter_by(show_id=slot_show.id).count() == 4


class TestAddSlots:

    def test_add_slots_does_not_delete_existing(self, db, slot_show):
        from auditions.utils import generate_slots, add_slots
        from auditions.models import AuditionSlot
        generate_slots(slot_show, [{'date': '2026-06-01', 'start_time': '19:00', 'total_hours': '0.5'}])
        original_count = AuditionSlot.query.filter_by(show_id=slot_show.id).count()
        add_slots(slot_show, [{'date': '2026-06-02', 'start_time': '19:00', 'total_hours': '0.5'}])
        new_count = AuditionSlot.query.filter_by(show_id=slot_show.id).count()
        assert new_count == original_count * 2


class TestAssignSlot:

    def test_assigns_first_available_slot(self, db, slot_show, slot, actor):
        from auditions.models import Registration
        from auditions.utils import assign_slot
        reg = Registration(user_id=actor.id, show_id=slot_show.id)
        db.session.add(reg)
        assign_slot(slot_show, reg)
        db.session.commit()
        assert reg.status == 'confirmed'
        assert reg.slot_id == slot.id

    def test_waitlists_when_no_slots(self, db, slot_show, actor):
        from auditions.models import Registration
        from auditions.utils import assign_slot
        reg = Registration(user_id=actor.id, show_id=slot_show.id)
        db.session.add(reg)
        assign_slot(slot_show, reg)
        db.session.commit()
        assert reg.status == 'waitlisted'
        assert reg.slot_id is None

    def test_waitlists_when_all_slots_full(self, db, slot_show, slot, actor):
        from auditions.models import Registration, AuditionSlot
        from auditions.utils import assign_slot
        # Fill the slot
        slot.current_count = slot.capacity
        db.session.commit()
        reg = Registration(user_id=actor.id, show_id=slot_show.id)
        db.session.add(reg)
        assign_slot(slot_show, reg)
        db.session.commit()
        assert reg.status == 'waitlisted'

    def test_increments_slot_count(self, db, slot_show, slot, actor):
        from auditions.models import Registration, AuditionSlot
        from auditions.utils import assign_slot
        reg = Registration(user_id=actor.id, show_id=slot_show.id)
        db.session.add(reg)
        assign_slot(slot_show, reg)
        db.session.commit()
        db.session.refresh(slot)
        assert slot.current_count == 1


class TestPromoteFromWaitlist:

    def test_promotes_oldest_waitlisted(self, db, slot_show, slot, admin):
        from auditions.models import Registration, User
        from auditions.utils import promote_from_waitlist
        from datetime import datetime, timedelta

        # Create two waitlisted actors
        u2 = User(email='actor2@test.com', first_name='B', last_name='B',
                  role='actor', contact_email_ok=True,
                  accept_other_role=True, comfortable_performing=True, equity_or_actra=False)
        u2.set_password('pass')
        u3 = User(email='actor3@test.com', first_name='C', last_name='C',
                  role='actor', contact_email_ok=True,
                  accept_other_role=True, comfortable_performing=True, equity_or_actra=False)
        u3.set_password('pass')
        db.session.add_all([u2, u3])
        db.session.commit()

        # Fill the slot first
        slot.current_count = slot.capacity
        db.session.commit()

        r2 = Registration(user_id=u2.id, show_id=slot_show.id, status='waitlisted')
        db.session.add(r2)
        db.session.commit()
        r3 = Registration(user_id=u3.id, show_id=slot_show.id, status='waitlisted')
        db.session.add(r3)
        db.session.commit()

        # Free the slot
        slot.current_count = 0
        db.session.commit()

        promoted = promote_from_waitlist(slot_show.id)
        assert promoted.id == r2.id  # oldest (r2) promoted first
        assert promoted.status == 'confirmed'

    def test_returns_none_when_no_waitlist(self, db, slot_show):
        from auditions.utils import promote_from_waitlist
        result = promote_from_waitlist(slot_show.id)
        assert result is None
