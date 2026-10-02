import csv
import io
import re

from flask import (current_app, flash, make_response, redirect, render_template, request,
                   url_for)
from flask_login import current_user
from sqlalchemy import func, or_

from auth.decorators import read_admin_required
from auth.models import db
from notifications.core import get_mail, send_logged_email
from respectful_space import respectful_space_bp
from respectful_space.forms import CheckListForm, SignForm
from respectful_space.models import (POLICY_VERSION, RespectfulSpaceSignature, current_season,
                                     local_time)


@respectful_space_bp.app_template_filter('rs_local_time')
def _rs_local_time(value):
    return local_time(value)


@respectful_space_bp.context_processor
def _template_helpers():
    return {'POLICY_VERSION': POLICY_VERSION}


# ---------------------------------------------------------------------------
# Public: read and sign
# ---------------------------------------------------------------------------

@respectful_space_bp.route('/', methods=['GET', 'POST'])
def sign():
    form = SignForm()

    if request.method == 'GET':
        form.production.data = request.args.get('show', '')[:255]
        if current_user.is_authenticated:
            form.first_name.data = current_user.first_name
            form.last_name.data = current_user.last_name
            form.email.data = current_user.email

    if form.validate_on_submit():
        if form.website.data:   # honeypot tripped — pretend it worked
            return redirect(url_for('respectful_space.thanks'))

        sig = RespectfulSpaceSignature(
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            email=form.email.data.strip().lower(),
            production=(form.production.data or '').strip() or None,
            signature_name=' '.join(form.signature_name.data.split()),
            policy_version=POLICY_VERSION,
            season=current_season(),
            ip_address=request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0][:64],
            user_agent=(request.user_agent.string or '')[:500],
            user_id=current_user.id if current_user.is_authenticated else None,
        )
        db.session.add(sig)
        db.session.commit()
        _send_confirmation(sig)
        return redirect(url_for('respectful_space.thanks', name=sig.first_name))

    return render_template('respectful_space/sign.html', form=form)


@respectful_space_bp.route('/thanks')
def thanks():
    return render_template('respectful_space/thanks.html', name=request.args.get('name', ''))


def _send_confirmation(sig):
    """Email the signer a copy of what they agreed to (best effort)."""
    try:
        html_body = render_template('respectful_space/email/confirmation.html', sig=sig)
        send_logged_email(
            get_mail(),
            to=sig.email,
            subject='Your Theatre Aurora Respectful Space Policy confirmation',
            html_body=html_body,
            email_type='respectful_space_signed',
            user_id=sig.user_id,
        )
    except Exception as e:  # never lose a signature because email failed
        current_app.logger.error(f'Respectful Space confirmation email failed: {e}')


# ---------------------------------------------------------------------------
# Admin: who has signed
# ---------------------------------------------------------------------------

def _filtered_signatures():
    season = request.args.get('season', current_season())
    q = (request.args.get('q') or '').strip()

    query = RespectfulSpaceSignature.query
    if season != 'all':
        query = query.filter(RespectfulSpaceSignature.season == season)
    if q:
        like = f'%{q.lower()}%'
        query = query.filter(or_(
            func.lower(RespectfulSpaceSignature.first_name + ' ' + RespectfulSpaceSignature.last_name).like(like),
            RespectfulSpaceSignature.email.like(like),
            func.lower(RespectfulSpaceSignature.production).like(like),
        ))
    return season, q, query.order_by(RespectfulSpaceSignature.signed_at.desc()).all()


@respectful_space_bp.route('/admin/')
@read_admin_required
def admin():
    season, q, signatures = _filtered_signatures()
    seasons = [s for (s,) in db.session.query(RespectfulSpaceSignature.season)
               .distinct().order_by(RespectfulSpaceSignature.season.desc())]
    if current_season() not in seasons:
        seasons.insert(0, current_season())
    return render_template('respectful_space/admin.html', signatures=signatures,
                           season=season, seasons=seasons, q=q,
                           sign_url=url_for('respectful_space.sign', _external=True))


@respectful_space_bp.route('/admin/export')
@read_admin_required
def export():
    season, _, signatures = _filtered_signatures()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['First name', 'Last name', 'Email', 'Show / role', 'Signature',
                     'Signed (Toronto time)', 'Season', 'Policy version', 'IP address'])
    for s in signatures:
        writer.writerow([s.first_name, s.last_name, s.email, s.production or '', s.signature_name,
                         local_time(s.signed_at), s.season, s.policy_version, s.ip_address or ''])
    response = make_response(out.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = (
        f'attachment; filename=respectful_space_signatures_{season}.csv')
    return response


@respectful_space_bp.route('/admin/check', methods=['GET', 'POST'])
@read_admin_required
def check():
    """Paste a cast/crew list and see who still needs to sign."""
    form = CheckListForm()
    results = None
    if form.validate_on_submit():
        results = [_lookup(line) for line in _split_people(form.people.data)]
    return render_template('respectful_space/check.html', form=form, results=results,
                           season=current_season(),
                           sign_url=url_for('respectful_space.sign', _external=True))


def _split_people(text):
    """One person per line; also split on commas/semicolons when a line holds
    several email addresses (as pasted from an email's To: field)."""
    people = []
    for line in text.splitlines():
        emails = re.findall(r'[\w.+\'-]+@[\w-]+(?:\.[\w-]+)+', line)
        if len(emails) > 1:
            people.extend(emails)
        elif line.strip():
            people.append(line.strip())
    return people


def _lookup(entry):
    """Latest signature for an email address (or, failing that, a full name)."""
    match = re.search(r'[\w.+\'-]+@[\w-]+(?:\.[\w-]+)+', entry)
    query = RespectfulSpaceSignature.query
    if match:
        query = query.filter(RespectfulSpaceSignature.email == match.group(0).lower())
    else:
        name = ' '.join(entry.split()).lower()
        query = query.filter(func.lower(
            RespectfulSpaceSignature.first_name + ' ' + RespectfulSpaceSignature.last_name) == name)
    latest = query.order_by(RespectfulSpaceSignature.signed_at.desc()).first()

    if latest is None:
        status = 'missing'
    elif latest.season == current_season() and latest.is_current_version:
        status = 'signed'
    else:
        status = 'outdated'
    return {'entry': entry, 'signature': latest, 'status': status}
