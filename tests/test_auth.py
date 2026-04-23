"""Tests for actor and admin authentication routes."""
import pytest
from auditions.models import User
from tests.conftest import login_as, login_actor, login_admin


class TestActorRegistration:

    def test_register_page_loads(self, client):
        r = client.get('/auditions/register')
        assert r.status_code == 200
        assert b'Create Your Account' in r.data

    def test_successful_registration(self, client, db):
        r = client.post('/auditions/register', data={
            'first_name': 'Jane',
            'last_name': 'Smith',
            'email': 'jane@example.com',
            'phone': '416-555-1234',
            'pronouns': 'she/her',
            'contact_email_ok': 'yes',
            'accept_other_role': 'yes',
            'comfortable_performing': 'yes',
            'equity_or_actra': 'no',
            'password': 'SecurePass1!',
            'confirm_password': 'SecurePass1!',
        }, follow_redirects=True)
        assert r.status_code == 200
        user = User.query.filter_by(email='jane@example.com').first()
        assert user is not None
        assert user.first_name == 'Jane'
        assert user.role == 'actor'

    def test_duplicate_email_rejected(self, client, actor):
        r = client.post('/auditions/register', data={
            'first_name': 'Other',
            'last_name': 'Person',
            'email': actor.email,  # already taken
            'password': 'SecurePass1!',
            'confirm_password': 'SecurePass1!',
            'contact_email_ok': 'yes',
            'accept_other_role': 'yes',
            'comfortable_performing': 'yes',
            'equity_or_actra': 'no',
        }, follow_redirects=True)
        assert User.query.filter_by(email=actor.email).count() == 1

    def test_password_mismatch_rejected(self, client, db):
        r = client.post('/auditions/register', data={
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'new@example.com',
            'password': 'SecurePass1!',
            'confirm_password': 'DifferentPass!',
            'contact_email_ok': 'yes',
            'accept_other_role': 'yes',
            'comfortable_performing': 'yes',
            'equity_or_actra': 'no',
        }, follow_redirects=True)
        assert User.query.filter_by(email='new@example.com').first() is None

    def test_pronouns_other_stored_as_custom_value(self, client, db):
        client.post('/auditions/register', data={
            'first_name': 'Alex',
            'last_name': 'Jones',
            'email': 'alex@example.com',
            'pronouns': 'other',
            'pronouns_other': 'ze/zir',
            'password': 'SecurePass1!',
            'confirm_password': 'SecurePass1!',
            'contact_email_ok': 'yes',
            'accept_other_role': 'yes',
            'comfortable_performing': 'yes',
            'equity_or_actra': 'no',
        }, follow_redirects=True)
        user = User.query.filter_by(email='alex@example.com').first()
        assert user is not None
        assert user.pronouns == 'ze/zir'


class TestActorLogin:

    def test_login_page_loads(self, client):
        r = client.get('/auditions/login')
        assert r.status_code == 200
        assert b'Log In' in r.data

    def test_valid_login_redirects_to_dashboard(self, client, actor):
        r = login_actor(client, actor)
        assert r.status_code == 200
        assert b'My Auditions' in r.data

    def test_wrong_password_rejected(self, client, actor):
        r = login_as(client, actor.email, 'WrongPassword!')
        assert b'Invalid email or password' in r.data

    def test_unknown_email_rejected(self, client, db):
        r = login_as(client, 'nobody@example.com', 'SomePass1!')
        assert b'Invalid email or password' in r.data

    def test_admin_login_redirects_to_admin_dashboard(self, client, admin):
        r = login_admin(client, admin)
        assert r.status_code == 200
        assert b'Auditions Dashboard' in r.data


class TestAdminLogin:

    def test_admin_login_page_loads(self, client):
        r = client.get('/auditions/admin/login')
        assert r.status_code == 200

    def test_actor_cannot_use_admin_login(self, client, actor):
        r = login_as(client, actor.email, 'ActorPass1!')
        # Actor logs in fine but shouldn't see admin dashboard
        r2 = client.get('/auditions/admin/dashboard', follow_redirects=False)
        assert r2.status_code in (302, 403)

    def test_admin_login_route_rejects_actor(self, client, actor):
        r = client.post('/auditions/admin/login', data={
            'email': actor.email,
            'password': 'ActorPass1!',
        }, follow_redirects=True)
        assert b'Invalid admin credentials' in r.data


class TestLogout:

    def test_logout_redirects_to_login(self, client, actor):
        login_actor(client, actor)
        r = client.get('/auditions/logout', follow_redirects=True)
        assert b'Log In' in r.data or b'logged out' in r.data

    def test_protected_page_requires_login(self, client):
        r = client.get('/auditions/my-auditions', follow_redirects=False)
        assert r.status_code == 302
        assert '/login' in r.headers['Location']
