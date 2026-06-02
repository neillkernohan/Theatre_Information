"""
Background send loop.  Runs in a daemon thread per campaign.
Uses Flask app context so SQLAlchemy works from the thread.
"""
import hashlib
import hmac
import time
import threading
from datetime import datetime
from urllib.parse import urlencode

_active_campaigns = {}  # campaign_id -> threading.Event (set to pause/stop)

_UNSUBSCRIBE_FOOTER = """
<div style="margin-top:32px;padding-top:16px;border-top:1px solid #e0e0e0;
            font-family:sans-serif;font-size:12px;color:#888;text-align:center;">
  You are receiving this email because you are a patron of Theatre Aurora.<br>
  <a href="{unsubscribe_url}" style="color:#888;">Unsubscribe</a>
</div>
"""


def _unsubscribe_url(base_url, email, secret_key):
    token = hmac.new(
        secret_key.encode(),
        email.lower().strip().encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{base_url}/unsubscribe?{urlencode({'email': email, 'token': token})}"


def send_campaign(app, campaign_id):
    """Spawn a background thread that sends all pending recipients."""
    if campaign_id in _active_campaigns:
        return  # already running

    stop_event = threading.Event()
    _active_campaigns[campaign_id] = stop_event

    def _run():
        from .models import EmailCampaign, EmailRecipient, db
        from .gmail_api import send_message

        with app.app_context():
            try:
                campaign = EmailCampaign.query.get(campaign_id)
                if not campaign:
                    return

                campaign.status = 'sending'
                if not campaign.started_at:
                    campaign.started_at = datetime.utcnow()
                db.session.commit()

                import os
                secret_key = app.config['SECRET_KEY']
                # BASE_URL should be set in .env, e.g. https://theatreaurora.com
                base_url = os.getenv('BASE_URL', '').rstrip('/')

                pending = (
                    EmailRecipient.query
                    .filter_by(campaign_id=campaign_id, status='pending')
                    .all()
                )

                for recipient in pending:
                    if stop_event.is_set():
                        campaign.status = 'paused'
                        db.session.commit()
                        break

                    # Personalise body: swap {{first_name}} / {{last_name}} if present
                    body = campaign.body_html
                    if recipient.first_name:
                        body = body.replace('{{first_name}}', recipient.first_name)
                    if recipient.last_name:
                        body = body.replace('{{last_name}}', recipient.last_name)

                    # Append unsubscribe footer with a pre-signed one-click link
                    footer = _UNSUBSCRIBE_FOOTER.format(
                        unsubscribe_url=_unsubscribe_url(base_url, recipient.email, secret_key)
                    )
                    body = body + footer

                    to_name = ' '.join(filter(None, [recipient.first_name, recipient.last_name]))
                    try:
                        send_message(
                            campaign.sender,
                            recipient.email,
                            to_name or None,
                            campaign.subject,
                            body,
                        )
                        recipient.status = 'sent'
                        recipient.sent_at = datetime.utcnow()
                        campaign.sent_count += 1
                    except Exception as exc:
                        recipient.status = 'failed'
                        recipient.error_message = str(exc)[:500]
                        campaign.failed_count += 1

                    db.session.commit()
                    # 1 email / 2 seconds — looks human, avoids spam-filter volume spikes
                    time.sleep(2)

                else:
                    campaign.status = 'completed'
                    campaign.completed_at = datetime.utcnow()
                    db.session.commit()

            except Exception as exc:
                with app.app_context():
                    campaign = EmailCampaign.query.get(campaign_id)
                    if campaign:
                        campaign.status = 'failed'
                        db.session.commit()
                raise
            finally:
                _active_campaigns.pop(campaign_id, None)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def pause_campaign(campaign_id):
    event = _active_campaigns.get(campaign_id)
    if event:
        event.set()


def is_running(campaign_id):
    return campaign_id in _active_campaigns
