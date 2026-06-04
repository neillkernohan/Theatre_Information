"""
Scan a sender account's Gmail inbox for delivery failure / bounce messages,
extract the bounced recipient addresses, and add them to the MySQL
Unsubscribed table so they are excluded from all future campaigns.

Bounce messages are identified by Gmail's standard search query.
The bounced address is extracted from RFC-3464 DSN parts
(message/delivery-status → Final-Recipient header) with a regex
fallback for non-standard mailers.
"""

import base64
import email
import os
import re

import mysql.connector
from googleapiclient.discovery import build

from .gmail_api import credentials_from_token_data, refresh_if_needed, token_data_from_credentials


# Gmail search that catches virtually all bounce/NDR messages
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


def _extract_bounced_address(raw_bytes):
    """Return the bounced email address from a raw RFC-2822 message, or None."""
    msg = email.message_from_bytes(raw_bytes)

    # Walk all MIME parts looking for message/delivery-status (RFC 3464)
    for part in msg.walk():
        if part.get_content_type() == 'message/delivery-status':
            payload = part.get_payload(decode=False)
            if isinstance(payload, list):
                payload = ''.join(str(p) for p in payload)
            m = _FINAL_RECIPIENT_RE.search(str(payload))
            if m:
                return m.group(1).strip().lower()

    # Fallback: look for a To: address in the first text/plain part
    for part in msg.walk():
        if part.get_content_type() == 'text/plain':
            text = part.get_payload(decode=True)
            if text:
                text = text.decode('utf-8', errors='replace')
                # Lines like: "The following address(es) failed:"
                # followed by the address on the next line
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    if 'failed' in line.lower() or 'undeliverable' in line.lower():
                        # Check the next few lines for an email address
                        for j in range(i + 1, min(i + 5, len(lines))):
                            m = _EMAIL_RE.search(lines[j])
                            if m:
                                return m.group(0).lower()

    return None


def _mysql_connect():
    return mysql.connector.connect(
        host=os.getenv('MYSQL_HOST'),
        user=os.getenv('MYSQL_USER'),
        password=os.getenv('MYSQL_PASSWORD'),
        database=os.getenv('MYSQL_DATABASE'),
    )


def process_bounces(sender_account, max_messages=500):
    """
    Scan sender_account's Gmail inbox for bounces.

    Returns a dict:
        scanned   – number of bounce messages examined
        added     – addresses newly added to Unsubscribed
        skipped   – addresses already in Unsubscribed
        addresses – list of newly added addresses
    """
    token_data = sender_account.get_token_data()
    creds = credentials_from_token_data(token_data)
    creds = refresh_if_needed(creds)

    # Persist refreshed token
    new_data = token_data_from_credentials(creds)
    if new_data['token'] != token_data.get('token'):
        sender_account.set_token_data(new_data)

    service = build('gmail', 'v1', credentials=creds)

    # Search for bounce messages (only INBOX + sent to us)
    results = service.users().messages().list(
        userId='me',
        q=_BOUNCE_QUERY,
        maxResults=max_messages,
        labelIds=['INBOX'],
    ).execute()

    messages = results.get('messages', [])
    scanned = 0
    added = []
    skipped = 0

    db = _mysql_connect()
    cur = db.cursor()

    # Fetch existing unsubscribed addresses for fast lookup
    cur.execute('SELECT LOWER(email) FROM Unsubscribed')
    already_unsub = {row[0] for row in cur.fetchall()}

    for msg_ref in messages:
        try:
            msg = service.users().messages().get(
                userId='me',
                id=msg_ref['id'],
                format='raw',
            ).execute()
            raw = base64.urlsafe_b64decode(msg['raw'])
            bounced = _extract_bounced_address(raw)
            scanned += 1

            if not bounced:
                continue

            if bounced in already_unsub:
                skipped += 1
                continue

            cur.execute(
                'INSERT IGNORE INTO Unsubscribed (email) VALUES (%s)',
                (bounced,)
            )
            db.commit()
            already_unsub.add(bounced)
            added.append(bounced)

        except Exception:
            continue

    db.close()

    return {
        'scanned': scanned,
        'added': len(added),
        'skipped': skipped,
        'addresses': added,
    }
