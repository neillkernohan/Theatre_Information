"""Tests for the Respectful Space Policy sign-off pages."""
from datetime import date, datetime

from respectful_space.models import (POLICY_VERSION, RespectfulSpaceSignature, current_season,
                                     season_for)


def _login(client, email, password):
    # Don't follow the post-login redirect: the minimal test app has no 'home' page.
    r = client.post('/auth/login', data={'email': email, 'password': password})
    assert r.status_code == 302


def login_actor(client, actor):
    _login(client, actor.email, 'ActorPass1!')


def login_admin(client, admin):
    _login(client, admin.email, 'AdminPass1!')


def _sign(client, **overrides):
    data = {
        'first_name': 'Pat', 'last_name': 'Lee', 'email': 'Pat@Example.com',
        'production': 'Mamma Mia! — cast', 'agree': 'y', 'signature_name': 'pat  lee',
    }
    data.update(overrides)
    return client.post('/respectful-space/', data=data, follow_redirects=False)


def _add(db, email, season=None, version=POLICY_VERSION, first='Sam', last='Doe'):
    db.session.add(RespectfulSpaceSignature(
        first_name=first, last_name=last, email=email, signature_name=f'{first} {last}',
        policy_version=version, season=season or current_season(), signed_at=datetime.utcnow()))
    db.session.commit()


def test_season_for():
    assert season_for(date(2026, 10, 2)) == '2026-27'
    assert season_for(date(2027, 8, 31)) == '2026-27'
    assert season_for(date(2027, 9, 1)) == '2027-28'


def test_policy_page_is_public(client):
    r = client.get('/respectful-space/?show=Annie')
    assert r.status_code == 200
    assert b'Respectful Space Policy' in r.data
    assert b'value="Annie"' in r.data


def test_signing_records_signature(client, db):
    r = _sign(client)
    assert r.status_code == 302 and '/respectful-space/thanks' in r.location
    sig = RespectfulSpaceSignature.query.one()
    assert sig.email == 'pat@example.com'
    assert sig.signature_name == 'pat lee'
    assert sig.policy_version == POLICY_VERSION
    assert sig.season == current_season()


def test_must_tick_agree(client, db):
    r = _sign(client, agree='')
    assert r.status_code == 200
    assert RespectfulSpaceSignature.query.count() == 0


def test_signature_must_match_name(client, db):
    r = _sign(client, signature_name='Someone Else')
    assert r.status_code == 200
    assert b'should match' in r.data
    assert RespectfulSpaceSignature.query.count() == 0


def test_honeypot_discards_bots(client, db):
    r = _sign(client, website='http://spam.example')
    assert r.status_code == 302
    assert RespectfulSpaceSignature.query.count() == 0


def test_admin_requires_staff(client, actor):
    login_actor(client, actor)
    assert client.get('/respectful-space/admin/').status_code == 403


def test_admin_lists_and_exports(client, admin, db):
    _add(db, 'sam@example.com')
    login_admin(client, admin)
    r = client.get('/respectful-space/admin/')
    assert r.status_code == 200 and b'sam@example.com' in r.data
    r = client.get('/respectful-space/admin/export')
    assert r.headers['Content-Type'].startswith('text/csv')
    assert b'sam@example.com' in r.data


def test_check_cast_list(client, admin, db):
    _add(db, 'signed@example.com')
    _add(db, 'old@example.com', season='2020-21')
    _add(db, 'oldversion@example.com', version='1999-01')
    _add(db, 'x@example.com', first='Byname', last='Person')
    login_admin(client, admin)
    r = client.post('/respectful-space/admin/check', data={
        'people': 'Signed@example.com\nold@example.com, oldversion@example.com\n'
                  'Byname  Person\nnobody@example.com'})
    assert r.status_code == 200
    html = r.data.decode()
    assert html.count('>Signed<') == 2
    assert html.count('Needs to re-sign') == 2
    assert html.count('>Not signed<') == 1
