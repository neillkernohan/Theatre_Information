import json
import os

from flask import (
    current_app, flash, jsonify, redirect, render_template,
    request, session, url_for,
)
from flask_login import current_user, login_required

from auth.decorators import manage_shows_required
from auth.models import db
from . import bulk_email_bp
from .models import EmailCampaign, EmailRecipient, SenderAccount, AUDIENCE_LABELS
from .audiences import (
    resolve_audience, get_available_seasons, get_available_marketing_lists,
)
from .gmail_api import (
    get_oauth_flow, get_authenticated_email, token_data_from_credentials,
)
from . import sender as send_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _force_https(url):
    """Upgrade an http:// URL to https://.

    Apache terminates TLS and proxies to Flask as http://, so both
    url_for(..., _external=True) and request.url come back http even though the
    public URL is https. OAuth needs the https form — both for redirect-URI
    matching at Google and for oauthlib's secure-transport check on the
    authorization response.
    """
    if url.startswith('http://'):
        return 'https://' + url[len('http://'):]
    return url


def _oauth_redirect_uri():
    return _force_https(url_for('bulk_email.oauth_callback', _external=True))


# ---------------------------------------------------------------------------
# Open tracking pixel (public — no login required)
# ---------------------------------------------------------------------------

# Minimal 1×1 transparent GIF
_TRANSPARENT_GIF = (
    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
    b'\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00'
    b'\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02'
    b'\x44\x01\x00\x3b'
)


@bulk_email_bp.route('/track/<token>.gif')
def track_open(token):
    from .models import EmailRecipient
    from datetime import datetime
    recipient = EmailRecipient.query.filter_by(tracking_token=token).first()
    if recipient:
        if not recipient.opened_at:
            recipient.opened_at = datetime.utcnow()
            # Increment campaign opened_count on first open only
            campaign = recipient.campaign
            if campaign:
                campaign.opened_count = (campaign.opened_count or 0) + 1
        recipient.open_count = (recipient.open_count or 0) + 1
        db.session.commit()

    from flask import Response
    return Response(
        _TRANSPARENT_GIF,
        mimetype='image/gif',
        headers={
            'Cache-Control': 'no-store, no-cache, must-revalidate',
            'Pragma': 'no-cache',
        }
    )


# ---------------------------------------------------------------------------
# Dashboard / campaign list
# ---------------------------------------------------------------------------

@bulk_email_bp.route('/')
@manage_shows_required
def index():
    campaigns = EmailCampaign.query.order_by(EmailCampaign.created_at.desc()).all()
    accounts = SenderAccount.query.filter_by(is_active=True).all()
    return render_template('bulk_email/index.html', campaigns=campaigns, accounts=accounts)


# ---------------------------------------------------------------------------
# Sender account management
# ---------------------------------------------------------------------------

@bulk_email_bp.route('/debug-redirect')
@manage_shows_required
def debug_redirect():
    return f"<pre>redirect_uri = {_oauth_redirect_uri()}</pre>"


@bulk_email_bp.route('/accounts')
@manage_shows_required
def accounts():
    accs = SenderAccount.query.order_by(SenderAccount.email).all()
    return render_template('bulk_email/accounts.html', accounts=accs)


@bulk_email_bp.route('/accounts/add')
@manage_shows_required
def add_account():
    flow = get_oauth_flow(_oauth_redirect_uri())
    auth_url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent',  # force consent so we always get a refresh token
        include_granted_scopes='false',
    )
    session['gmail_oauth_state'] = state
    # PKCE: the callback builds a fresh Flow, so carry the one-time code_verifier
    # generated here across the redirect. Without it, the token exchange fails
    # with "Missing code verifier".
    session['gmail_code_verifier'] = flow.code_verifier
    return redirect(auth_url)


@bulk_email_bp.route('/accounts/callback')
@manage_shows_required
def oauth_callback():
    state = session.pop('gmail_oauth_state', None)
    if not state or state != request.args.get('state'):
        flash('OAuth state mismatch — please try again.', 'danger')
        return redirect(url_for('bulk_email.accounts'))

    if 'error' in request.args:
        flash(f'Google authorisation denied: {request.args["error"]}', 'danger')
        return redirect(url_for('bulk_email.accounts'))

    flow = get_oauth_flow(_oauth_redirect_uri())
    flow.code_verifier = session.pop('gmail_code_verifier', None)
    flow.fetch_token(
        authorization_response=_force_https(request.url),
        state=state,
    )
    credentials = flow.credentials
    email = get_authenticated_email(credentials)

    existing = SenderAccount.query.filter_by(email=email).first()
    if existing:
        existing.set_token_data(token_data_from_credentials(credentials))
        existing.is_active = True
        db.session.commit()
        flash(f'{email} re-authorised successfully.', 'success')
    else:
        acc = SenderAccount(email=email, display_name=email)
        acc.set_token_data(token_data_from_credentials(credentials))
        db.session.add(acc)
        db.session.commit()
        flash(f'{email} added as a sender account.', 'success')

    return redirect(url_for('bulk_email.accounts'))


@bulk_email_bp.route('/accounts/<int:account_id>/display-name', methods=['POST'])
@manage_shows_required
def update_display_name(account_id):
    acc = SenderAccount.query.get_or_404(account_id)
    acc.display_name = request.form.get('display_name', acc.email).strip() or acc.email
    db.session.commit()
    flash('Display name updated.', 'success')
    return redirect(url_for('bulk_email.accounts'))


@bulk_email_bp.route('/accounts/<int:account_id>/remove', methods=['POST'])
@manage_shows_required
def remove_account(account_id):
    acc = SenderAccount.query.get_or_404(account_id)
    acc.is_active = False
    db.session.commit()
    flash(f'{acc.email} removed from sender accounts.', 'success')
    return redirect(url_for('bulk_email.accounts'))


# ---------------------------------------------------------------------------
# Audience preview (AJAX)
# ---------------------------------------------------------------------------

@bulk_email_bp.route('/audience-count')
@manage_shows_required
def audience_count():
    audience_type = request.args.get('type', '')
    params = {}
    if audience_type == 'marketing_list':
        params['list_name'] = request.args.get('list_name', '')
    elif audience_type == 'season_buyers':
        params['season'] = request.args.get('season', '')

    try:
        recipients = resolve_audience(audience_type, params)
        return jsonify({'count': len(recipients)})
    except Exception as exc:
        return jsonify({'count': 0, 'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# Edit existing draft/paused campaign
# ---------------------------------------------------------------------------

@bulk_email_bp.route('/campaign/<int:campaign_id>/edit', methods=['GET', 'POST'])
@manage_shows_required
def edit_campaign(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    if campaign.status not in ('draft', 'paused'):
        flash('Only draft or paused campaigns can be edited.', 'warning')
        return redirect(url_for('bulk_email.campaign_detail', campaign_id=campaign_id))

    accounts = SenderAccount.query.filter_by(is_active=True).all()

    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        body_html = request.form.get('body_html', '').strip()
        sender_id = request.form.get('sender_account_id', type=int)

        errors = []
        if not subject:
            errors.append('Subject is required.')
        if not body_html:
            errors.append('Email body is required.')
        if not sender_id:
            errors.append('Please select a sender account.')

        if errors:
            for e in errors:
                flash(e, 'danger')
        else:
            campaign.subject = subject
            campaign.body_html = body_html
            campaign.sender_account_id = sender_id
            db.session.commit()
            flash('Campaign updated.', 'success')
            return redirect(url_for('bulk_email.campaign_detail', campaign_id=campaign_id))

    return render_template('bulk_email/edit_campaign.html', campaign=campaign, accounts=accounts)


# ---------------------------------------------------------------------------
# Compose / create campaign
# ---------------------------------------------------------------------------

@bulk_email_bp.route('/compose', methods=['GET', 'POST'])
@manage_shows_required
def compose():
    accounts = SenderAccount.query.filter_by(is_active=True).all()
    seasons = []
    marketing_lists = []
    try:
        seasons = get_available_seasons()
        marketing_lists = get_available_marketing_lists()
    except Exception:
        pass

    if request.method == 'POST':
        sender_id = request.form.get('sender_account_id', type=int)
        subject = request.form.get('subject', '').strip()
        body_html = request.form.get('body_html', '').strip()
        audience_type = request.form.get('audience_type', '')
        list_name = request.form.get('list_name', '').strip()
        season = request.form.get('season', '').strip()

        errors = []
        if not sender_id:
            errors.append('Please select a sender account.')
        if not subject:
            errors.append('Subject is required.')
        if not body_html:
            errors.append('Email body is required.')
        if not audience_type:
            errors.append('Please select an audience.')
        if audience_type == 'marketing_list' and not list_name:
            errors.append('Please enter a marketing list name.')
        if audience_type == 'season_buyers' and not season:
            errors.append('Please select a season.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template(
                'bulk_email/compose.html',
                accounts=accounts, seasons=seasons,
                marketing_lists=marketing_lists,
                audience_labels=AUDIENCE_LABELS,
                form=request.form,
            )

        params = {}
        if audience_type == 'marketing_list':
            params['list_name'] = list_name
        elif audience_type == 'season_buyers':
            params['season'] = season

        # Resolve recipients now so we store them
        try:
            audience = resolve_audience(audience_type, params)
        except Exception as exc:
            flash(f'Error loading audience: {exc}', 'danger')
            return render_template(
                'bulk_email/compose.html',
                accounts=accounts, seasons=seasons,
                marketing_lists=marketing_lists,
                audience_labels=AUDIENCE_LABELS,
                form=request.form,
            )

        if not audience:
            flash('The selected audience returned 0 recipients. Campaign not created.', 'warning')
            return render_template(
                'bulk_email/compose.html',
                accounts=accounts, seasons=seasons,
                marketing_lists=marketing_lists,
                audience_labels=AUDIENCE_LABELS,
                form=request.form,
            )

        campaign = EmailCampaign(
            sender_account_id=sender_id,
            subject=subject,
            body_html=body_html,
            audience_type=audience_type,
            audience_params=json.dumps(params) if params else None,
            status='draft',
            total_count=len(audience),
        )
        db.session.add(campaign)
        db.session.flush()  # get campaign.id

        for row in audience:
            db.session.add(EmailRecipient(
                campaign_id=campaign.id,
                email=row['email'],
                first_name=row.get('first_name', ''),
                last_name=row.get('last_name', ''),
                status='pending',
            ))
        db.session.commit()

        flash(f'Campaign created with {len(audience)} recipients.', 'success')
        return redirect(url_for('bulk_email.campaign_detail', campaign_id=campaign.id))

    return render_template(
        'bulk_email/compose.html',
        accounts=accounts,
        seasons=seasons,
        marketing_lists=marketing_lists,
        audience_labels=AUDIENCE_LABELS,
        form={},
    )


# ---------------------------------------------------------------------------
# Campaign detail + send control
# ---------------------------------------------------------------------------

@bulk_email_bp.route('/campaign/<int:campaign_id>')
@manage_shows_required
def campaign_detail(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    is_running = send_service.is_running(campaign_id)
    failed = (
        EmailRecipient.query
        .filter_by(campaign_id=campaign_id, status='failed')
        .all()
    )
    return render_template(
        'bulk_email/campaign_detail.html',
        campaign=campaign,
        is_running=is_running,
        failed=failed,
    )


@bulk_email_bp.route('/campaign/<int:campaign_id>/progress')
@manage_shows_required
def campaign_progress(campaign_id):
    """AJAX endpoint polled by the detail page for live progress."""
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    return jsonify({
        'status': campaign.status,
        'total': campaign.total_count,
        'sent': campaign.sent_count,
        'opened': campaign.opened_count or 0,
        'failed': campaign.failed_count,
        'pending': campaign.total_count - campaign.sent_count - campaign.failed_count,
        'is_running': send_service.is_running(campaign_id),
    })


@bulk_email_bp.route('/campaign/<int:campaign_id>/send', methods=['POST'])
@manage_shows_required
def start_send(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    if campaign.status not in ('draft', 'paused'):
        flash('Campaign cannot be started in its current state.', 'warning')
        return redirect(url_for('bulk_email.campaign_detail', campaign_id=campaign_id))
    if send_service.is_running(campaign_id):
        flash('Campaign is already sending.', 'info')
        return redirect(url_for('bulk_email.campaign_detail', campaign_id=campaign_id))
    send_service.send_campaign(current_app._get_current_object(), campaign_id)
    flash('Sending started.', 'success')
    return redirect(url_for('bulk_email.campaign_detail', campaign_id=campaign_id))


@bulk_email_bp.route('/campaign/<int:campaign_id>/pause', methods=['POST'])
@manage_shows_required
def pause_send(campaign_id):
    send_service.pause_campaign(campaign_id)
    flash('Pause signal sent — in-flight email will finish before stopping.', 'info')
    return redirect(url_for('bulk_email.campaign_detail', campaign_id=campaign_id))


@bulk_email_bp.route('/campaign/<int:campaign_id>/test', methods=['POST'])
@manage_shows_required
def send_test(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    test_email = request.form.get('test_email', '').strip()
    if not test_email:
        flash('Please enter a test email address.', 'danger')
        return redirect(url_for('bulk_email.campaign_detail', campaign_id=campaign_id))

    from .gmail_api import send_message
    from .sender import _UNSUBSCRIBE_FOOTER, _unsubscribe_url
    import os

    body = campaign.body_html.replace('{{first_name}}', 'Test').replace('{{last_name}}', 'Recipient')
    base_url = os.getenv('BASE_URL', '').rstrip('/')
    footer = _UNSUBSCRIBE_FOOTER.format(
        unsubscribe_url=_unsubscribe_url(base_url, test_email, current_app.config['SECRET_KEY'])
    )
    body = body + footer

    try:
        send_message(campaign.sender, test_email, None, f'[TEST] {campaign.subject}', body)
        flash(f'Test email sent to {test_email}.', 'success')
    except Exception as exc:
        flash(f'Test send failed: {exc}', 'danger')

    return redirect(url_for('bulk_email.campaign_detail', campaign_id=campaign_id))


@bulk_email_bp.route('/campaign/<int:campaign_id>/delete', methods=['POST'])
@manage_shows_required
def delete_campaign(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    if campaign.status == 'sending':
        flash('Cannot delete a campaign that is currently sending.', 'danger')
        return redirect(url_for('bulk_email.campaign_detail', campaign_id=campaign_id))
    db.session.delete(campaign)
    db.session.commit()
    flash('Campaign deleted.', 'success')
    return redirect(url_for('bulk_email.index'))
