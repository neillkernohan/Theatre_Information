"""
Scan a sender account's Gmail inbox for delivery failure / bounce messages,
extract the bounced recipient addresses, and add them to the MySQL
Unsubscribed table so they are excluded from all future campaigns.

Runs in a background thread; progress is tracked in _jobs dict so the
UI can poll for live status.
"""

import base64
import email as email_lib
import os
import re
import threading
from datetime import datetime

import mysql.connector
from googleapiclient.discovery import build

from .gmail_api import credentials_from_token_data, refresh_if_needed, token_data_from_credentials

# ------------------------------------------------------------------
# Gmail search that catches virtually all bounce/NDR messages
# ------------------------------------------------------------------
_BOUNCE_QUERY = (
    'from:mailer-daemon '
    'OR from:postmaster '
    'OR subject:"delivery status notification" '
    'OR subject:"undelivered mail returned" '
    'OR subject:"delivery failure" '
    'OR subject:"mail delivery failed" '
    'OR subject:"returned mail"'
)

_FINAL_RECIPIENT_RE = re.compile(
    r'Final-Recipient\s*:\s*rfc822\s*;\s*([^\s\r\n]+)',
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')

# ------------------------------------------------------------------
# In-memory job tracker  {account_id: status_dict}
# ------------------------------------------------------------------
_jobs = {}


def get_job_status(account_id):
    return _jobs.get(account_id)


def is_running(account_id):
    job = _jobs.get(account_id)
    return job is not None and job['state'] == 'running'


# ------------------------------------------------------------------
# Parsing helpers
# ------------------------------------------------------------------

def _extract_from_full(msg_data):
    """Extract bounced address from a Gmail API 'full' format message dict."""
    def _walk(parts):
        for part in parts:
            mime = part.get('mimeType', '')
            if mime == 'message/delivery-status':
                # The delivery status body is base64-encoded
                body_data = part.get('body', {}).get('data', '')
                if body_data:
                    text = base64.urlsafe_b64decode(body_data + '==').decode('utf-8', errors='replace')
                    m = _FINAL_RECIPIENT_RE.search(text)
                    if m:
                        return m.group(1).strip().lower()
            # Recurse into sub-parts
            sub = part.get('parts', [])
            if sub:
                result = _walk(sub)
                if result:
                    return result
        return None

    payload = msg_data.get('payload', {})
    parts = payload.get('parts', [])
    result = _walk(parts)
    if result:
        return result

    # Fallback: scan plain-text body for an address after "failed" keyword
    for part in parts:
        if part.get('mimeType') == 'text/plain':
            data = part.get('body', {}).get('data', '')
            if data:
                text = base64.urlsafe_b64decode(data + '==').decode('utf-8', errors='replace')
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    if 'failed' in line.lower() or 'undeliverable' in line.lower():
                        for j in range(i + 1, min(i + 5, len(lines))):
                            m = _EMAIL_RE.search(lines[j])
                            if m:
                                return m.group(0).lower()
    return None


# ------------------------------------------------------------------
# MySQL helper
# ------------------------------------------------------------------

def _mysql_connect():
    return mysql.connector.connect(
        host=os.getenv('MYSQL_HOST'),
        user=os.getenv('MYSQL_USER'),
        password=os.getenv('MYSQL_PASSWORD'),
        database=os.getenv('MYSQL_DATABASE'),
    )


# ------------------------------------------------------------------
# Background job
# ------------------------------------------------------------------

def start_bounce_job(app, sender_account):
    account_id = sender_account.id
    if is_running(account_id):
        return

    _jobs[account_id] = {
        'state': 'running',
        'found': 0,
        'scanned': 0,
        'added': 0,
        'skipped': 0,
        'addresses': [],
        'error': None,
        'started_at': datetime.utcnow().strftime('%H:%M:%S'),
    }

    def _run():
        from auth.models import db
        with app.app_context():
            job = _jobs[account_id]
            try:
                token_data = sender_account.get_token_data()
                creds = credentials_from_token_data(token_data)
                creds = refresh_if_needed(creds)

                new_data = token_data_from_credentials(creds)
                if new_data['token'] != token_data.get('token'):
                    sender_account.set_token_data(new_data)
                    db.session.commit()

                service = build('gmail', 'v1', credentials=creds)

                # Step 1: list matching message IDs
                results = service.users().messages().list(
                    userId='me',
                    q=_BOUNCE_QUERY,
                    maxResults=500,
                    labelIds=['INBOX'],
                ).execute()
                messages = results.get('messages', [])
                job['found'] = len(messages)

                # Load existing suppressed addresses
                db_conn = _mysql_connect()
                cur = db_conn.cursor()
                cur.execute('SELECT LOWER(email) FROM Unsubscribed')
                already_unsub = {row[0] for row in cur.fetchall()}

                # Step 2: fetch each message (full format — faster than raw)
                for msg_ref in messages:
                    try:
                        msg = service.users().messages().get(
                            userId='me',
                            id=msg_ref['id'],
                            format='full',
                        ).execute()
                        bounced = _extract_from_full(msg)
                        job['scanned'] += 1

                        if not bounced:
                            continue
                        if bounced in already_unsub:
                            job['skipped'] += 1
                            continue

                        cur.execute(
                            'INSERT IGNORE INTO Unsubscribed (email) VALUES (%s)',
                            (bounced,)
                        )
                        db_conn.commit()
                        already_unsub.add(bounced)
                        job['added'] += 1
                        job['addresses'].append(bounced)

                    except Exception:
                        continue

                db_conn.close()
                job['state'] = 'done'

            except Exception as exc:
                job['state'] = 'error'
                job['error'] = str(exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
