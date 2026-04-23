"""Tests for admin routes: dashboard, show management, registration management."""
import pytest
from datetime import datetime, timedelta
from tests.conftest import login_admin, login_actor


class TestAdminAccess:

    def test_dashboard_requires_admin(self, client, actor):
        login_actor(client, actor)
        r = client.get('/auditions/admin/dashboard', follow_redirects=False)
        assert r.status_code == 403

    def test_dashboard_loads_for_admin(self, client, admin):
        login_admin(client, admin)
        r = client.get('/auditions/admin/dashboard')
        assert r.status_code == 200
        assert b'Auditions Dashboard' in r.data

    def test_unauthenticated_redirected(self, client):
        r = client.get('/auditions/admin/dashboard', follow_redirects=False)
        assert r.status_code == 302


class TestShowManagement:

    def test_create_show_page_loads(self, client, admin):
        login_admin(client, admin)
        r = client.get('/auditions/admin/shows/new')
        assert r.status_code == 200

    def test_create_slot_show(self, client, admin, db):
        from auditions.models import Show
        login_admin(client, admin)
        r = client.post('/auditions/admin/shows/new', data={
            'title': 'New Slot Show',
            'scheduling_mode': 'slot',
            'slot_duration_minutes': '15',
            'allow_choice': True,
            'registration_open': (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'registration_close': (datetime.utcnow() + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M'),
            'custom_fields_json': '[]',
        }, follow_redirects=True)
        assert Show.query.filter_by(title='New Slot Show').first() is not None

    def test_create_block_show(self, client, admin, db):
        from auditions.models import Show
        login_admin(client, admin)
        r = client.post('/auditions/admin/shows/new', data={
            'title': 'New Block Show',
            'scheduling_mode': 'block',
            'max_per_block': '8',
            'block_duration_minutes': '90',
            'allow_choice': False,
            'registration_open': (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'registration_close': (datetime.utcnow() + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M'),
            'custom_fields_json': '[]',
        }, follow_redirects=True)
        show = Show.query.filter_by(title='New Block Show').first()
        assert show is not None
        assert show.max_per_block == 8

    def test_show_detail_loads(self, client, admin, slot_show):
        login_admin(client, admin)
        r = client.get(f'/auditions/admin/shows/{slot_show.id}')
        assert r.status_code == 200
        assert slot_show.title.encode() in r.data

    def test_update_show_status(self, client, admin, slot_show, db):
        from auditions.models import Show
        login_admin(client, admin)
        client.post(f'/auditions/admin/shows/{slot_show.id}/status',
                    data={'status': 'closed'}, follow_redirects=True)
        db.session.refresh(slot_show)
        assert slot_show.status == 'closed'

    def test_cannot_delete_show_with_registrations(self, client, admin, slot_show, slot, actor, db):
        from auditions.models import Registration
        reg = Registration(user_id=actor.id, show_id=slot_show.id,
                           slot_id=slot.id, status='confirmed')
        db.session.add(reg)
        db.session.commit()
        login_admin(client, admin)
        r = client.post(f'/auditions/admin/shows/{slot_show.id}/delete',
                        follow_redirects=True)
        assert b'Cannot delete' in r.data
        from auditions.models import Show
        assert Show.query.get(slot_show.id) is not None

    def test_generate_slots(self, client, admin, slot_show, db):
        import json
        from auditions.models import AuditionSlot
        login_admin(client, admin)
        dates = [{'date': '2026-07-01', 'start_time': '19:00', 'total_hours': '1'}]
        client.post(f'/auditions/admin/shows/{slot_show.id}/generate-slots',
                    data={'audition_dates_json': json.dumps(dates)},
                    follow_redirects=True)
        assert AuditionSlot.query.filter_by(show_id=slot_show.id).count() == 4


class TestRegistrationManagement:

    @pytest.fixture
    def registration(self, db, actor, slot_show, slot):
        from auditions.models import Registration
        reg = Registration(user_id=actor.id, show_id=slot_show.id,
                           slot_id=slot.id, status='confirmed')
        db.session.add(reg)
        slot.current_count = 1
        db.session.commit()
        return reg

    def test_registration_detail_loads(self, client, admin, registration):
        login_admin(client, admin)
        r = client.get(f'/auditions/admin/registrations/{registration.id}')
        assert r.status_code == 200
        assert b'Jane' in r.data

    def test_update_registration_status_to_callback(self, client, admin, registration, db):
        from auditions.models import Registration
        login_admin(client, admin)
        client.post(f'/auditions/admin/registrations/{registration.id}/status',
                    data={'status': 'callback'}, follow_redirects=True)
        db.session.refresh(registration)
        assert registration.status == 'callback'

    def test_update_registration_status_to_cancelled_frees_slot(
            self, client, admin, registration, slot, db):
        login_admin(client, admin)
        client.post(f'/auditions/admin/registrations/{registration.id}/status',
                    data={'status': 'cancelled'}, follow_redirects=True)
        db.session.refresh(slot)
        assert slot.current_count == 0

    def test_save_admin_notes(self, client, admin, registration, db):
        from auditions.models import Registration
        login_admin(client, admin)
        client.post(f'/auditions/admin/registrations/{registration.id}/notes',
                    data={'notes': 'Strong singer, very confident.'}, follow_redirects=True)
        db.session.refresh(registration)
        assert registration.notes == 'Strong singer, very confident.'

    def test_create_and_assign_tag(self, client, admin, registration, db):
        from auditions.models import Tag
        login_admin(client, admin)
        # Create a tag
        client.post('/auditions/admin/tags/create', data={'name': 'strong dancer'})
        tag = Tag.query.filter_by(name='strong dancer').first()
        assert tag is not None
        # Assign to registration
        client.post(f'/auditions/admin/registrations/{registration.id}/tags',
                    data={'tag_ids': [tag.id]}, follow_redirects=True)
        db.session.refresh(registration)
        assert any(t.name == 'strong dancer' for t in registration.tags)

    def test_show_detail_filter_by_status(self, client, admin, slot_show, registration):
        login_admin(client, admin)
        r = client.get(f'/auditions/admin/shows/{slot_show.id}?status=confirmed')
        assert r.status_code == 200
        assert b'Jane' in r.data

    def test_show_detail_filter_excludes_other_status(self, client, admin, slot_show, registration):
        login_admin(client, admin)
        # Filter for waitlisted — Jane is confirmed, so the table should say no matches
        r = client.get(f'/auditions/admin/shows/{slot_show.id}?status=waitlisted')
        assert r.status_code == 200
        assert b'No registrations match' in r.data

    def test_show_detail_search_match(self, client, admin, slot_show, registration):
        login_admin(client, admin)
        r = client.get(f'/auditions/admin/shows/{slot_show.id}?q=Jane')
        assert r.status_code == 200
        assert b'Jane' in r.data

    def test_show_detail_search_no_match(self, client, admin, slot_show, registration):
        login_admin(client, admin)
        r = client.get(f'/auditions/admin/shows/{slot_show.id}?q=zzznomatch')
        assert r.status_code == 200
        assert b'No registrations match' in r.data
