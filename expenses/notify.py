"""Expense notification emails, sent and logged via notifications.core.

Who hears about what:
- Claim (re)submitted or approved by a producer → whoever reviews it next.
- Returned, rejected, signed off or paid → the submitter.
"""
from flask import render_template, url_for

from expenses.models import person_name
from expenses.parsing import money
from notifications.core import get_mail, send_logged_email


def _send(*, to, user_id, subject, email_type, claim, greeting, paragraphs, comment=None,
          commenter=None):
    html = render_template(
        'expenses/email.html', claim=claim, greeting=greeting, paragraphs=paragraphs,
        comment=comment, commenter=commenter,
        link=url_for('expenses.claim_detail', claim_id=claim.id, _external=True))
    send_logged_email(get_mail(), to=to, subject=subject, html_body=html,
                      email_type=email_type, user_id=user_id)


def needs_review(claim, reviewers, step: str) -> None:
    """step: 'approve' (producer) or 'sign off' (VP of Finance / President)."""
    for reviewer in reviewers:
        _send(to=reviewer.email, user_id=None,
              subject=f'Please {step}: {claim.title} ({money(claim.total_cents)})',
              email_type='expense_review', claim=claim, greeting=reviewer.name,
              paragraphs=[f'A claim is waiting for you to {step}.'])


def to_submitter(claim, headline: str, actor, comment, next_step: str) -> None:
    _send(to=claim.submitter.email, user_id=claim.submitter_id,
          subject=f'{headline}: {claim.title}',
          email_type=f'expense_{headline.lower().replace(" ", "_")}', claim=claim,
          greeting=person_name(claim.submitter),
          paragraphs=[f'Your claim was {headline.lower()} by {person_name(actor)}.', next_step],
          comment=comment, commenter=person_name(actor))
