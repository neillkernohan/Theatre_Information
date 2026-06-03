"""
Gmail API helpers: OAuth2 flow + sending individual messages.
"""
import base64
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ['https://mail.google.com/']


def _client_config():
    """Build the OAuth client config from the shared GOOGLE_CLIENT_* env vars.

    This is the same OAuth client the main-site Google login uses, so the
    bulk-email redirect URI only has to be registered on one client. (We no
    longer read a separate client_secret.json — that pointed at a different
    client whose redirect URIs weren't kept in sync.)
    """
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    if not client_id or not client_secret:
        raise RuntimeError(
            'GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set — '
            'bulk-email OAuth cannot start.'
        )
    return {
        'web': {
            'client_id': client_id,
            'client_secret': client_secret,
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'auth_provider_x509_cert_url': 'https://www.googleapis.com/oauth2/v1/certs',
        }
    }


def get_oauth_flow(redirect_uri):
    return Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )


def credentials_from_token_data(token_data):
    return Credentials(
        token=token_data.get('token'),
        refresh_token=token_data.get('refresh_token'),
        token_uri=token_data.get('token_uri'),
        client_id=token_data.get('client_id'),
        client_secret=token_data.get('client_secret'),
        scopes=token_data.get('scopes'),
    )


def refresh_if_needed(credentials):
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    return credentials


def token_data_from_credentials(credentials):
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes,
    }


def build_message(sender_email, sender_name, to_email, to_name, subject, body_html):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    if sender_name:
        msg['From'] = f'{sender_name} <{sender_email}>'
    else:
        msg['From'] = sender_email
    if to_name:
        msg['To'] = f'{to_name} <{to_email}>'
    else:
        msg['To'] = to_email
    msg.attach(MIMEText(body_html, 'html'))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {'raw': raw}


def send_message(sender_account, to_email, to_name, subject, body_html):
    """
    Send one email via the Gmail API.
    Returns True on success, raises on failure.
    sender_account is a SenderAccount model instance.
    """
    token_data = sender_account.get_token_data()
    creds = credentials_from_token_data(token_data)
    creds = refresh_if_needed(creds)

    # Persist refreshed token back to the model
    new_data = token_data_from_credentials(creds)
    if new_data['token'] != token_data.get('token'):
        sender_account.set_token_data(new_data)

    service = build('gmail', 'v1', credentials=creds)
    message = build_message(
        sender_account.email,
        sender_account.display_name,
        to_email,
        to_name,
        subject,
        body_html,
    )
    service.users().messages().send(userId='me', body=message).execute()
    return True


def get_authenticated_email(credentials):
    """Return the email address associated with freshly obtained credentials."""
    service = build('gmail', 'v1', credentials=credentials)
    profile = service.users().getProfile(userId='me').execute()
    return profile.get('emailAddress', '')
