"""Tests for public/actor-facing routes: shows, registration, cancellation."""
import pytest
from datetime import datetime, timedelta
from tests.conftest import login_actor


class TestShowsList:

    def test_shows_list_loads(self, client):
        r = client.get('/auditions/shows')
        assert r.status_code == 200

    def test_open_show_appears(self, client, slot_show):
        r = client.get('/auditions/shows')
        assert slot_show.title.encode() in r.data

    def test_draft_show_not_visible(self, client, db):
        from auditions.models import Show
        show = Show(
            title='Hidden Draft',
            scheduling_mode='slot',
            slot_duration_minutes=15,
            allow_choice=True,
            registration_open=datetime.utcnow() - timedelta(days=1),
            registration_close=datetime.utcnow() + timedelta(days=30),
            status='draft',
        )
        db.session.add(show)
        db.session.commit()
        r = client.get('/auditions/shows')
        assert b'Hidden Draft' not in r.data

    def test_closed_registration_not_visible(self, client, db):
        from auditions.models import Show
        show = Show(
            title='Past Show',
            scheduling_mode='slot',
            slot_duration_minutes=15,
            allow_choice=True,
            registration_open=datetime.utcnow() - timedelta(days=30),
            registration_close=datetime.utcnow() - timedelta(days=1),
            status='open',
        )
        db.session.add(show)
        db.session.commit()
        r = client.get('/auditions/shows')
        assert b'Past Show' not in r.data


class TestRegisterForShow:

    def test_redirects_to_login_if_not_authenticated(self, client, slot_show):
        r = client.get(f'/auditions/shows/{slot_show.id}/register',
                       follow_redirects=False)
        assert r.status_code == 302
        assert '/login' in r.headers['Location']

    def test_registration_page_loads_for_actor(self, client, actor, slot_show, slot):
        login_actor(client, actor)
        r = client.get(f'/auditions/shows/{slot_show.id}/register')
        assert r.status_code == 200
        assert slot_show.title.encode() in r.data

    def test_actor_can_register_for_slot(self, client, actor, slot_show, slot, db):
        from auditions.models import Registration
        login_actor(client, actor)
        with client.application.extensions['mail'].record_messages() as outbox:
            r = client.post(f'/auditions/shows/{slot_show.id}/register', data={
                'slot_id': slot.id,
            }, follow_redirects=True)
        reg = Registration.query.filter_by(
            user_id=actor.id, show_id=slot_show.id
        ).first()
        assert reg is not None
        assert reg.status == 'confirmed'
        assert reg.slot_id == slot.id

    def test_slot_count_incremented(self, client, actor, slot_show, slot, db):
        from auditions.models import AuditionSlot
        login_actor(client, actor)
        client.post(f'/auditions/shows/{slot_show.id}/register', data={
            'slot_id': slot.id,
        }, follow_redirects=True)
        db.session.refresh(slot)
        assert slot.current_count == 1

    def test_waitlisted_when_no_slot_chosen(self, client, actor, slot_show, db):
        from auditions.models import Registration
        login_actor(client, actor)
        r = client.post(f'/auditions/shows/{slot_show.id}/register', data={},
                        follow_redirects=True)
        reg = Registration.query.filter_by(
            user_id=actor.id, show_id=slot_show.id
        ).first()
        assert reg is not None
        assert reg.status == 'waitlisted'

    def test_cannot_register_twice(self, client, actor, slot_show, slot, db):
        from auditions.models import Registration
        login_actor(client, actor)
        # First registration
        client.post(f'/auditions/shows/{slot_show.id}/register', data={
            'slot_id': slot.id,
        }, follow_redirects=True)
        # Try again
        r = client.get(f'/auditions/shows/{slot_show.id}/register',
                       follow_redirects=True)
        assert b'already registered' in r.data
        assert Registration.query.filter_by(
            user_id=actor.id, show_id=slot_show.id
        ).filter(Registration.status != 'cancelled').count() == 1

    def test_closed_show_blocks_registration(self, client, actor, db):
        from auditions.models import Show
        closed = Show(
            title='Closed Show',
            scheduling_mode='slot',
            slot_duration_minutes=15,
            allow_choice=True,
            registration_open=datetime.utcnow() - timedelta(days=30),
            registration_close=datetime.utcnow() - timedelta(days=1),
            status='open',
        )
        db.session.add(closed)
        db.session.commit()
        login_actor(client, actor)
        r = client.get(f'/auditions/shows/{closed.id}/register',
                       follow_redirects=True)
        assert b'not currently open' in r.data


class TestCancelRegistration:

    def test_actor_can_cancel(self, client, actor, slot_show, slot, db):
        from auditions.models import Registration
        login_actor(client, actor)
        client.post(f'/auditions/shows/{slot_show.id}/register', data={
            'slot_id': slot.id,
        }, follow_redirects=True)
        reg = Registration.query.filter_by(user_id=actor.id, show_id=slot_show.id).first()
        r = client.post(f'/auditions/registrations/{reg.id}/cancel',
                        follow_redirects=True)
        db.session.refresh(reg)
        assert reg.status == 'cancelled'
        assert reg.slot_id is None

    def test_cancel_frees_slot_count(self, client, actor, slot_show, slot, db):
        from auditions.models import Registration, AuditionSlot
        login_actor(client, actor)
        client.post(f'/auditions/shows/{slot_show.id}/register', data={
            'slot_id': slot.id,
        }, follow_redirects=True)
        reg = Registration.query.filter_by(user_id=actor.id, show_id=slot_show.id).first()
        client.post(f'/auditions/registrations/{reg.id}/cancel', follow_redirects=True)
        db.session.refresh(slot)
        assert slot.current_count == 0

    def test_cancel_promotes_waitlisted(self, client, actor, slot_show, slot, db):
        """Cancelling a confirmed booking should auto-confirm the next waitlisted actor."""
        from auditions.models import Registration, User
        # Create a second actor who will be waitlisted
        u2 = User(email='waitlisted@test.com', first_name='W', last_name='W',
                  role='actor', contact_email_ok=True,
                  accept_other_role=True, comfortable_performing=True, equity_or_actra=False)
        u2.set_password('pass')
        db.session.add(u2)
        db.session.commit()

        # Actor 1 takes the only slot
        login_actor(client, actor)
        client.post(f'/auditions/shows/{slot_show.id}/register', data={
            'slot_id': slot.id,
        }, follow_redirects=True)
        client.get('/auditions/logout')

        # Actor 2 registers — slot is full so waitlisted
        from tests.conftest import login_as
        login_as(client, u2.email, 'pass')
        client.post(f'/auditions/shows/{slot_show.id}/register', data={},
                    follow_redirects=True)
        r2 = Registration.query.filter_by(user_id=u2.id, show_id=slot_show.id).first()
        assert r2.status == 'waitlisted'
        client.get('/auditions/logout')

        # Actor 1 cancels — actor 2 should be promoted
        login_actor(client, actor)
        reg1 = Registration.query.filter_by(user_id=actor.id, show_id=slot_show.id).first()
        client.post(f'/auditions/registrations/{reg1.id}/cancel', follow_redirects=True)

        db.session.refresh(r2)
        assert r2.status == 'confirmed'

    def test_other_actor_cannot_cancel(self, client, actor, slot_show, slot, db, admin):
        from auditions.models import Registration
        login_actor(client, actor)
        client.post(f'/auditions/shows/{slot_show.id}/register', data={
            'slot_id': slot.id,
        }, follow_redirects=True)
        reg = Registration.query.filter_by(user_id=actor.id, show_id=slot_show.id).first()
        client.get('/auditions/logout')

        # Admin tries to cancel via actor route — should be blocked
        from tests.conftest import login_admin
        login_admin(client, admin)
        r = client.post(f'/auditions/registrations/{reg.id}/cancel',
                        follow_redirects=True)
        db.session.refresh(reg)
        # Should still be confirmed (not cancelled by wrong user)
        assert reg.status == 'confirmed'
