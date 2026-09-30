"""Expenses: claims, approval routing, payments, QuickBooks export, setup."""
import csv
import io
from datetime import date, timedelta
from html import unescape
from pathlib import Path

import pytest

JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 100
PDF = b'%PDF-1.4\n' + b'x' * 100
TODAY = date.today()
PASSWORD = 'Passw0rd!'


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def make_user(db, email, first, role='actor'):
    from auth.models import User
    u = User(email=email, first_name=first, last_name='Test', role=role)
    u.set_password(PASSWORD)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def org(db):
    """Annie (produced by Pat), Oliver (no producer), VP of Finance, President,
    a volunteer, a super admin, two categories and a vendor."""
    from expenses.models import (ExpenseCategory, ExpenseRole, ExpenseShow,
                                 ExpenseShowProducer, ExpenseVendor)
    people = {
        'vol': make_user(db, 'vol@example.com', 'Val'),
        'pat': make_user(db, 'pat@example.com', 'Pat'),
        'vp': make_user(db, 'vp@example.com', 'Vic'),
        'prez': make_user(db, 'prez@example.com', 'Pres'),
        'admin': make_user(db, 'boss@example.com', 'Boss', role='super_admin'),
        'rando': make_user(db, 'rando@example.com', 'Rando'),
    }
    annie = ExpenseShow(name='Annie', season='2026-27', qb_class='Annie')
    annie.producers.append(ExpenseShowProducer(email='pat@example.com'))
    oliver = ExpenseShow(name='Oliver', season='2026-27', qb_class='Oliver')
    props = ExpenseCategory(label='Props', qb_account='Show Expenses:Props')
    lights = ExpenseCategory(label='Lighting', qb_account='Show Expenses:Technical Supplies')
    vendor = ExpenseVendor(name='Stage Lights Inc', email='billing@lights.example')
    db.session.add_all([annie, oliver, props, lights, vendor,
                        ExpenseRole(email='vp@example.com', role='vp_finance'),
                        ExpenseRole(email='prez@example.com', role='president')])
    db.session.commit()
    return {**people, 'annie': annie.id, 'oliver': oliver.id, 'props': props.id,
            'lights': lights.id, 'vendor': vendor.id}


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr('expenses.notify.send_logged_email',
                        lambda mail, **kw: sent.append(kw) or True)
    return sent


@pytest.fixture
def as_user(app, client):
    """Switch the test client to a different signed-in user."""
    def _as(email):
        client.get('/auth/logout')
        # Don't follow the post-login redirect: the minimal test app has no
        # main dashboard for staff landing pages to link to.
        r = client.post('/auth/login', data={'email': email, 'password': PASSWORD})
        assert r.status_code == 302, f'login failed for {email}'
        return client
    return _as


def new_claim(c, kind='reimbursement', **extra) -> int:
    r = c.post('/expenses/claims/new', data={'kind': kind, 'title': 'Props run', **extra})
    assert r.status_code == 302, r.get_data(as_text=True)
    return int(r.headers['Location'].rsplit('/', 1)[1])


def add_line(c, claim_id, category, files=None, **overrides):
    data = {'spent_on': TODAY.isoformat(), 'merchant': 'Home Depot', 'description': 'Lumber',
            'category_id': str(category), 'total': '$113.00', 'hst': '13.00', **overrides}
    if files:
        data['receipts'] = [(io.BytesIO(content), name) for name, content in files]
    return c.post(f'/expenses/claims/{claim_id}/lines', data=data,
                  content_type='multipart/form-data')


def submit(c, org, show=None, kind='reimbursement', description='Tape') -> int:
    extra = {'show_id': str(org[show])} if show else {}
    claim_id = new_claim(c, kind=kind, **extra)
    add_line(c, claim_id, org['props'], files=[('r.jpg', JPEG)], description=description)
    r = c.post(f'/expenses/claims/{claim_id}/submit')
    assert r.status_code == 302, r.get_data(as_text=True)
    return claim_id


def review(c, claim_id, decision, comment=''):
    return c.post(f'/expenses/claims/{claim_id}/review',
                  data={'decision': decision, 'comment': comment})


def pay(c, claim_id, **overrides):
    data = {'method': 'etransfer', 'paid_on': TODAY.isoformat(), 'reference': 'CA1234',
            **overrides}
    return c.post(f'/expenses/claims/{claim_id}/pay', data=data)


def claim(db, claim_id):
    from expenses.models import ExpenseClaim
    db.session.expire_all()
    return db.session.get(ExpenseClaim, claim_id)


def text(response) -> str:
    return unescape(response.get_data(as_text=True))


def to(outbox) -> list[str]:
    return [m['to'] for m in outbox]


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

class TestClaims:
    def test_requires_login(self, client):
        r = client.get('/expenses/')
        assert r.status_code == 302 and '/auth/login' in r.headers['Location']

    def test_reimbursement_happy_path(self, db, org, as_user, outbox):
        c = as_user('vol@example.com')
        claim_id = new_claim(c, show_id=str(org['annie']))
        assert add_line(c, claim_id, org['props'], files=[('receipt.jpg', JPEG)]).status_code == 302

        cl = claim(db, claim_id)
        line = cl.lines[0]
        assert (line.total_cents, line.hst_cents, line.subtotal_cents) == (11300, 1300, 10000)
        assert line.attachments[0].content_type == 'image/jpeg'
        assert '$113.00' in text(c.get(f'/expenses/claims/{claim_id}'))

        assert c.post(f'/expenses/claims/{claim_id}/submit').status_code == 302
        cl = claim(db, claim_id)
        assert cl.status == 'submitted'
        assert [e.action for e in cl.events] == ['created', 'submitted']
        assert 'Props run' in text(c.get('/expenses/'))
        # Locked once submitted.
        assert add_line(c, claim_id, org['props']).status_code == 409

    def test_cannot_submit_without_receipt(self, db, org, as_user):
        c = as_user('vol@example.com')
        claim_id = new_claim(c)
        add_line(c, claim_id, org['props'])
        r = c.post(f'/expenses/claims/{claim_id}/submit')
        assert r.status_code == 400
        assert '1 line(s) still need a receipt photo' in text(r)

        line_id = claim(db, claim_id).lines[0].id
        c.post(f'/expenses/claims/{claim_id}/files',
               data={'line_id': str(line_id), 'files': [(io.BytesIO(PDF), 'r.pdf')]},
               content_type='multipart/form-data')
        assert c.post(f'/expenses/claims/{claim_id}/submit').status_code == 302

    @pytest.mark.parametrize('overrides, message', [
        ({'total': 'abc'}, 'must be an amount'),
        ({'total': '0'}, 'more than zero'),
        ({'total': '10.005'}, 'two decimal places'),
        ({'hst': '20', 'total': '10'}, "HST can't be more than the total"),
        ({'spent_on': (TODAY + timedelta(days=2)).isoformat()}, "can't be in the future"),
        ({'merchant': ''}, 'Enter where it was bought'),
        ({'category_id': ''}, 'Choose a category'),
    ])
    def test_line_validation(self, db, org, as_user, overrides, message):
        c = as_user('vol@example.com')
        claim_id = new_claim(c)
        r = add_line(c, claim_id, org['props'], **overrides)
        assert r.status_code == 400 and message in text(r)
        assert claim(db, claim_id).lines == []

    def test_rejects_disguised_file_and_keeps_nothing(self, app, db, org, as_user):
        c = as_user('vol@example.com')
        claim_id = new_claim(c)
        folder = Path(app.config['EXPENSES_UPLOAD_DIR'])
        before = set(folder.iterdir()) if folder.exists() else set()
        r = add_line(c, claim_id, org['props'],
                     files=[('good.jpg', JPEG), ('evil.jpg', b'<script>alert(1)</script>')])
        assert r.status_code == 400 and "isn't a photo" in text(r)
        assert claim(db, claim_id).lines == []
        assert set(folder.iterdir()) == before

    def test_rejects_oversized_file(self, db, org, as_user):
        c = as_user('vol@example.com')
        claim_id = new_claim(c)
        r = add_line(c, claim_id, org['props'], files=[('big.jpg', JPEG + b'\x00' * 1024 * 1024)])
        assert r.status_code == 400 and 'larger than 1 MB' in text(r)

    def test_delete_draft_removes_files(self, app, db, org, as_user):
        from expenses import storage
        c = as_user('vol@example.com')
        claim_id = new_claim(c)
        add_line(c, claim_id, org['props'], files=[('r.jpg', JPEG)])
        with app.test_request_context():
            stored = storage.path_for(claim(db, claim_id).attachments[0].stored_name)
        assert stored.exists()
        c.post(f'/expenses/claims/{claim_id}/delete')
        assert claim(db, claim_id) is None and not stored.exists()

    def test_invoice_flow_and_duplicate_warning(self, db, org, as_user, outbox):
        c = as_user('vol@example.com')
        first = new_claim(c, kind='invoice', vendor=str(org['vendor']), invoice_number='INV-7')
        c.post(f'/expenses/claims/{first}/lines',
               data={'spent_on': TODAY.isoformat(), 'description': 'Rental',
                     'category_id': str(org['lights']), 'total': '565', 'hst': '65'})
        r = c.post(f'/expenses/claims/{first}/submit')
        assert 'Attach a copy of the invoice' in text(r)
        c.post(f'/expenses/claims/{first}/files', data={'files': [(io.BytesIO(PDF), 'i.pdf')]},
               content_type='multipart/form-data')
        assert c.post(f'/expenses/claims/{first}/submit').status_code == 302
        assert claim(db, first).payee_name == 'Stage Lights Inc'

        second = new_claim(c, kind='invoice', vendor=str(org['vendor']), invoice_number='inv-7')
        assert f'claim #{first}' in text(c.get(f'/expenses/claims/{second}'))

    def test_visibility(self, db, org, as_user, outbox):
        c = as_user('vol@example.com')
        draft = new_claim(c, show_id=str(org['annie']))
        claim_id = submit(c, org, show='annie')
        file_id = claim(db, claim_id).attachments[0].id

        assert as_user('boss@example.com').get(f'/expenses/claims/{draft}').status_code == 403
        rando = as_user('rando@example.com')
        assert rando.get(f'/expenses/claims/{claim_id}').status_code == 403
        assert rando.get(f'/expenses/files/{file_id}').status_code == 403

        pat = as_user('pat@example.com')
        r = pat.get(f'/expenses/files/{file_id}')
        assert r.status_code == 200 and r.data == JPEG
        assert r.headers['X-Content-Type-Options'] == 'nosniff'


# ---------------------------------------------------------------------------
# Approval routing
# ---------------------------------------------------------------------------

class TestApprovals:
    def test_show_claim_goes_producer_then_vp(self, db, org, as_user, outbox):
        claim_id = submit(as_user('vol@example.com'), org, show='annie')
        assert claim(db, claim_id).status == 'submitted'
        assert to(outbox) == ['pat@example.com']
        assert 'Please approve' in outbox[0]['subject']

        pat = as_user('pat@example.com')
        assert '1 claim waiting for you' in text(pat.get('/expenses/'))
        assert review(pat, claim_id, 'approve').status_code == 302
        assert claim(db, claim_id).status == 'approved'
        assert to(outbox)[1:] == ['vp@example.com']

        review(as_user('vp@example.com'), claim_id, 'approve', 'Looks good')
        cl = claim(db, claim_id)
        assert cl.status == 'signed_off'
        assert to(outbox)[2:] == ['vol@example.com']
        assert 'Looks good' in outbox[2]['html_body']
        assert [e.action for e in cl.events] == ['created', 'submitted', 'approved', 'signed off']

    def test_producers_own_claim_skips_to_vp(self, db, org, as_user, outbox):
        pat = as_user('pat@example.com')
        claim_id = submit(pat, org, show='annie')
        assert claim(db, claim_id).status == 'approved'
        assert to(outbox) == ['vp@example.com']
        assert review(pat, claim_id, 'approve').status_code == 409

    def test_general_and_no_producer_go_to_vp(self, db, org, as_user, outbox):
        c = as_user('vol@example.com')
        general = submit(c, org)
        oliver = submit(c, org, show='oliver')
        assert claim(db, general).status == claim(db, oliver).status == 'approved'
        assert 'no producer set up' in claim(db, oliver).events[-1].comment

    def test_vp_claims_signed_off_by_president(self, db, org, as_user, outbox):
        vp = as_user('vp@example.com')
        claim_id = submit(vp, org)
        assert to(outbox) == ['prez@example.com']
        assert review(vp, claim_id, 'approve').status_code == 409
        review(as_user('prez@example.com'), claim_id, 'approve')
        assert claim(db, claim_id).status == 'signed_off'

    def test_return_needs_comment_and_resubmit_restarts(self, db, org, as_user, outbox):
        claim_id = submit(as_user('vol@example.com'), org, show='annie')
        pat = as_user('pat@example.com')
        assert review(pat, claim_id, 'return').status_code == 400
        review(pat, claim_id, 'return', 'Receipt is blurry')
        assert claim(db, claim_id).status == 'returned'
        assert 'Receipt is blurry' in outbox[-1]['html_body']

        vol = as_user('vol@example.com')
        assert vol.post(f'/expenses/claims/{claim_id}/submit').status_code == 302
        assert claim(db, claim_id).status == 'submitted'
        assert outbox[-1]['to'] == 'pat@example.com'

    def test_reject_is_final(self, db, org, as_user, outbox):
        claim_id = submit(as_user('vol@example.com'), org)
        review(as_user('vp@example.com'), claim_id, 'reject', 'Not a theatre expense')
        assert claim(db, claim_id).status == 'rejected'
        assert as_user('vol@example.com').post(f'/expenses/claims/{claim_id}/submit').status_code == 409

    def test_only_current_reviewer_can_act(self, db, org, as_user, outbox):
        claim_id = submit(as_user('vol@example.com'), org, show='annie')
        vp = as_user('vp@example.com')
        assert vp.get(f'/expenses/claims/{claim_id}').status_code == 200
        assert review(vp, claim_id, 'approve').status_code == 409
        assert review(as_user('rando@example.com'), claim_id, 'approve').status_code == 403

    def test_approvals_page(self, db, org, as_user, outbox):
        claim_id = submit(as_user('vol@example.com'), org, show='annie')
        assert as_user('vol@example.com').get('/expenses/approvals').status_code == 403
        page = text(as_user('vp@example.com').get('/expenses/approvals'))
        assert f'#{claim_id}' in page and 'waiting on Pat Test' in page


# ---------------------------------------------------------------------------
# Payments & export
# ---------------------------------------------------------------------------

def signed_off(as_user, org, **kw) -> int:
    claim_id = submit(as_user('vol@example.com'), org, **kw)      # general → VP
    review(as_user('vp@example.com'), claim_id, 'approve')
    return claim_id


def read_csv(response) -> list[dict]:
    assert response.status_code == 200, response.get_data(as_text=True)
    return list(csv.DictReader(io.StringIO(response.get_data(as_text=True).lstrip('﻿'))))


class TestPayments:
    def test_vp_records_payment(self, db, org, as_user, outbox):
        claim_id = signed_off(as_user, org)
        vp = as_user('vp@example.com')
        assert '1 claim signed off and ready to pay' in text(vp.get('/expenses/'))
        assert 'Record payment of $113.00' in text(vp.get(f'/expenses/claims/{claim_id}'))

        assert pay(vp, claim_id).status_code == 302
        cl = claim(db, claim_id)
        assert cl.status == 'paid' and cl.payment.amount_cents == 11300
        assert outbox[-1]['subject'].startswith('Paid:')
        assert 'You were paid $113.00 by Interac e-Transfer #CA1234' in outbox[-1]['html_body']
        assert pay(vp, claim_id).status_code == 409

    def test_etransfer_email_from_profile(self, db, org, as_user, outbox):
        vol = as_user('vol@example.com')
        vol.post('/expenses/profile', data={'etransfer_email': 'Val.Bank@example.com'})
        claim_id = signed_off(as_user, org)
        assert 'val.bank@example.com' in text(as_user('vp@example.com').get(f'/expenses/claims/{claim_id}'))

    @pytest.mark.parametrize('overrides, message', [
        ({'method': ''}, 'Choose how it was paid'),
        ({'paid_on': (TODAY + timedelta(days=1)).isoformat()}, "can't be in the future"),
        ({'method': 'cheque', 'reference': ''}, 'Enter the cheque number'),
    ])
    def test_payment_validation(self, db, org, as_user, outbox, overrides, message):
        claim_id = signed_off(as_user, org)
        r = pay(as_user('vp@example.com'), claim_id, **overrides)
        assert r.status_code == 400 and message in text(r)

    def test_only_payers_can_pay(self, db, org, as_user, outbox):
        claim_id = signed_off(as_user, org)
        assert pay(as_user('boss@example.com'), claim_id).status_code == 409
        assert pay(as_user('prez@example.com'), claim_id).status_code == 302

    def test_undo_payment(self, db, org, as_user, outbox):
        claim_id = signed_off(as_user, org)
        vp = as_user('vp@example.com')
        pay(vp, claim_id)
        assert vp.post(f'/expenses/claims/{claim_id}/unpay', data={'reason': ''}).status_code == 400
        vp.post(f'/expenses/claims/{claim_id}/unpay', data={'reason': 'Wrong claim'})
        cl = claim(db, claim_id)
        assert cl.status == 'signed_off' and cl.payment is None

    def test_export(self, db, org, as_user, outbox):
        claim_id = signed_off(as_user, org, description='=HYPERLINK("http://evil")')
        vp = as_user('vp@example.com')
        pay(vp, claim_id)
        rows = read_csv(vp.get('/expenses/payments/export.csv?status=paid'))
        assert len(rows) == 1
        row = rows[0]
        assert (row['Payee'], row['QB account']) == ('Val Test', 'Show Expenses:Props')
        assert (row['Subtotal'], row['HST'], row['Total']) == ('100.00', '13.00', '113.00')
        assert row['QB tax code'] == 'HST ON - PSB Rebate (Purchases)'
        assert (row['Signed off by'], row['Paid by']) == ('Vic Test', 'Vic Test')
        assert row['Description'].startswith("'=")

    def test_export_access(self, db, org, as_user):
        assert as_user('vol@example.com').get('/expenses/payments/export.csv').status_code == 403
        assert as_user('boss@example.com').get('/expenses/payments').status_code == 200


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

class TestSetup:
    def test_access(self, db, org, as_user):
        assert as_user('vol@example.com').get('/expenses/setup').status_code == 403
        vp = as_user('vp@example.com')
        assert vp.get('/expenses/setup/shows').status_code == 200
        assert vp.get('/expenses/setup/roles').status_code == 403        # can't self-promote
        assert as_user('boss@example.com').get('/expenses/setup/roles').status_code == 200

    def test_show_and_producer(self, db, org, as_user):
        from expenses.models import ExpenseShow
        vp = as_user('vp@example.com')
        vp.post('/expenses/setup/shows', data={'name': 'Mamma Mia!', 'season': '2026-27'})
        show = ExpenseShow.query.filter_by(name='Mamma Mia!').one()
        assert show.qb_class == 'Mamma Mia!'
        vp.post(f'/expenses/setup/shows/{show.id}/producers', data={'email': 'New@Example.com'})
        db.session.expire_all()
        assert show.producer_emails == ['new@example.com']
        assert 'no account yet' in text(vp.get(f'/expenses/setup/shows/{show.id}'))

    def test_roles(self, db, org, as_user):
        from expenses.models import ExpenseRole
        boss = as_user('boss@example.com')
        boss.post('/expenses/setup/roles', data={'email': 'rando@example.com', 'role': 'vp_finance'})
        assert ExpenseRole.query.filter_by(email='rando@example.com').count() == 1

    def test_seed_categories(self, db):
        from expenses.models import ExpenseCategory
        from expenses.seed import CATEGORIES, seed
        db.session.add(ExpenseCategory(label='Props'))
        db.session.commit()
        assert 'Props' in seed() and seed() == []
        assert ExpenseCategory.query.filter_by(label='Props').one().qb_account == 'Show Expenses:Props'
        assert ExpenseCategory.query.count() == len(CATEGORIES)


# ---------------------------------------------------------------------------
# Reading receipts with AI (Claude is faked — no real API calls)
# ---------------------------------------------------------------------------

def real_jpeg() -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (3000, 2000), 'white').save(out, 'JPEG')
    return out.getvalue()


class FakeClaude:
    """Stands in for anthropic.Anthropic(); records the request it was sent."""

    def __init__(self, answer, stop_reason='end_turn'):
        import json
        from types import SimpleNamespace
        self.requests = []
        self.response = SimpleNamespace(
            stop_reason=stop_reason,
            content=[SimpleNamespace(type='text', text=json.dumps(answer))])
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.response


RECEIPT = {'document_type': 'receipt', 'merchant': 'Fabricland', 'date': '2026-09-20',
           'total': 84.75, 'hst': 9.75, 'description': 'Gold sequin trim',
           'category': 'Props', 'invoice_number': None, 'due_date': None}


@pytest.fixture
def claude(app, monkeypatch):
    """Turn the feature on and fake Claude. Call with the answer to return."""
    monkeypatch.setitem(app.config, 'EXPENSES_AI_ENABLED', True)

    def _fake(answer=RECEIPT, stop_reason='end_turn'):
        fake = FakeClaude(answer, stop_reason)
        monkeypatch.setattr('expenses.ai._client', lambda: fake)
        return fake
    return _fake


def extract(c, claim_id, file=None, attachment_id=None):
    data = {'attachment_id': str(attachment_id)} if attachment_id else {}
    if file:
        data['file'] = (io.BytesIO(file[1]), file[0])
    return c.post(f'/expenses/claims/{claim_id}/extract', data=data,
                  content_type='multipart/form-data')


class TestReceiptReading:
    def test_off_without_api_key(self, app, db, org, as_user, monkeypatch):
        monkeypatch.setitem(app.config, 'EXPENSES_AI_ENABLED', False)
        c = as_user('vol@example.com')
        claim_id = new_claim(c)
        assert extract(c, claim_id, file=('r.jpg', real_jpeg())).status_code == 404
        assert 'Fill in the details from the photo' not in text(c.get(f'/expenses/claims/{claim_id}'))

    def test_reads_receipt_photo(self, db, org, as_user, claude):
        fake = claude()
        c = as_user('vol@example.com')
        claim_id = new_claim(c)
        assert 'Fill in the details from the photo' in text(c.get(f'/expenses/claims/{claim_id}'))

        r = extract(c, claim_id, file=('r.jpg', real_jpeg()))
        assert r.status_code == 200, r.get_data(as_text=True)
        d = r.get_json()
        assert (d['merchant'], d['date'], d['total'], d['hst']) == \
            ('Fabricland', '2026-09-20', '84.75', '9.75')
        assert d['category_id'] == org['props']

        sent = fake.requests[0]
        assert sent['model'] == 'claude-opus-5'
        assert sent['fallbacks'] == 'default'
        image = sent['messages'][0]['content'][0]
        assert image['type'] == 'image' and image['source']['media_type'] == 'image/jpeg'
        # Big phone photos are shrunk before sending.
        from PIL import Image
        import base64
        sent_img = Image.open(io.BytesIO(base64.b64decode(image['source']['data'])))
        assert max(sent_img.size) <= 1568
        # Only this theatre's categories are allowed as answers.
        category_schema = sent['output_config']['format']['schema']['properties']['category']
        assert set(category_schema['anyOf'][0]['enum']) == {'Props', 'Lighting'}
        # Nothing was saved.
        assert claim(db, claim_id).lines == []

    def test_reads_attached_invoice_and_matches_vendor(self, db, org, as_user, claude):
        fake = claude({**RECEIPT, 'document_type': 'invoice', 'merchant': 'stage lights inc',
                       'invoice_number': 'INV-42', 'due_date': '2026-10-31',
                       'category': 'Lighting'})
        c = as_user('vol@example.com')
        claim_id = new_claim(c, kind='invoice')
        c.post(f'/expenses/claims/{claim_id}/files', data={'files': [(io.BytesIO(PDF), 'i.pdf')]},
               content_type='multipart/form-data')
        attachment_id = claim(db, claim_id).attachments[0].id
        assert 'Fill in from this invoice' in text(c.get(f'/expenses/claims/{claim_id}'))

        d = extract(c, claim_id, attachment_id=attachment_id).get_json()
        assert d['vendor_id'] == org['vendor']
        assert (d['invoice_number'], d['due_date']) == ('INV-42', '2026-10-31')
        assert fake.requests[0]['messages'][0]['content'][0]['type'] == 'document'

    def test_only_owner_while_editable(self, db, org, as_user, claude, outbox):
        claude()
        c = as_user('vol@example.com')
        draft = new_claim(c)
        submitted = submit(c, org)
        assert extract(c, submitted, file=('r.jpg', real_jpeg())).status_code == 409
        other = as_user('rando@example.com')
        assert extract(other, draft, file=('r.jpg', real_jpeg())).status_code == 403

    def test_rejects_non_image(self, db, org, as_user, claude):
        claude()
        c = as_user('vol@example.com')
        r = extract(c, new_claim(c), file=('notes.txt', b'hello'))
        assert r.status_code == 400 and "isn't a photo" in r.get_json()['error']

    def test_refusal_gives_friendly_error(self, db, org, as_user, claude):
        claude(stop_reason='refusal')
        c = as_user('vol@example.com')
        r = extract(c, new_claim(c), file=('r.jpg', real_jpeg()))
        assert r.status_code == 422 and 'fill in the details yourself' in r.get_json()['error']

    def test_answer_is_sanitised(self, app):
        from expenses.ai import _clean
        with app.app_context():
            d = _clean({'total': 10, 'hst': 20, 'date': '2026-13-45', 'category': 'Snacks',
                        'merchant': '  Rona  ', 'description': None}, ['Props'])
        assert d['hst'] is None and d['date'] is None and d['category'] is None
        assert (d['total'], d['merchant']) == ('10.00', 'Rona')

    def test_real_sdk_client_builds(self, app):
        """Guards against dependency clashes (e.g. an old trio pin breaks the
        SDK's HTTP layer on Python 3.13) that the fake client would hide."""
        from expenses.ai import _client
        with app.app_context():
            assert _client() is not None
