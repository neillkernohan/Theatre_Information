"""Respectful Space Policy sign-offs.

Anyone involved with the theatre (cast, crew, volunteers, members) signs the
policy online — no account needed. Each row is one signature; people re-sign
each season or whenever the policy changes, so we keep every row rather than
updating a single record per person.
"""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from auth.models import db

# Bump this whenever the policy wording in
# templates/respectful_space/_policy.html changes, so the admin page can tell
# who signed an older version.
POLICY_VERSION = '2026-06'

LOCAL_TZ = ZoneInfo('America/Toronto')


def season_for(d: date) -> str:
    """Theatre seasons run September to August: Oct 2026 → '2026-27'."""
    start = d.year if d.month >= 9 else d.year - 1
    return f'{start}-{(start + 1) % 100:02d}'


def current_season() -> str:
    return season_for(datetime.now(LOCAL_TZ).date())


def local_time(value: datetime | None) -> str:
    """Jinja filter: stored UTC timestamp → 'Sep 23, 2026 2:05 PM' in Toronto time."""
    if value is None:
        return ''
    if value.tzinfo is None:            # stored naive UTC
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TZ).strftime('%b %-d, %Y %-I:%M %p')


class RespectfulSpaceSignature(db.Model):
    __tablename__ = 'respectful_space_signatures'

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)   # lower-cased
    production = db.Column(db.String(255))      # show or role they're involved in
    signature_name = db.Column(db.String(255), nullable=False)
    policy_version = db.Column(db.String(20), nullable=False)
    season = db.Column(db.String(20), nullable=False, index=True)   # e.g. "2026-27"
    signed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(500))
    # Set when the signer happened to be logged in to theatreapps.
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    @property
    def full_name(self) -> str:
        return f'{self.first_name} {self.last_name}'.strip()

    @property
    def is_current_version(self) -> bool:
        return self.policy_version == POLICY_VERSION
