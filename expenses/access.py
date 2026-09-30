"""Who can see, approve, sign off and pay what. The rules, in one place:

| Claim                                   | Step 1: approve  | Step 2: sign off |
| --------------------------------------- | ---------------- | ---------------- |
| Show expense                            | a show producer  | VP of Finance    |
| Show expense by one of its producers    | (skipped)        | VP of Finance    |
| General expense                         | (skipped)        | VP of Finance    |
| Anything submitted by the VP of Finance | (as above)       | President        |

Nobody approves or signs off their own claim. A show with no producer set up
skips step 1 rather than leaving the claim stuck. The VP of Finance or the
President records payment of signed-off claims.

Expense roles and show producers are stored by email (see models.py). The
site's super admins administer expenses.
"""
from dataclasses import dataclass

from flask import g

from auth.models import User
from expenses.models import (APPROVED, DRAFT, PRESIDENT, SIGNED_OFF, SUBMITTED, VOID, VP_FINANCE,
                             ExpenseClaim, ExpenseRole, ExpenseShow, ExpenseShowProducer,
                             person_name)

PAYERS = (VP_FINANCE, PRESIDENT)


@dataclass(frozen=True)
class Reviewer:
    email: str
    name: str


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

def roles_of(user) -> set[str]:
    """Expense roles for a user, cached for the request."""
    cache = g.setdefault('_expense_roles', {})
    if user.email not in cache:
        cache[user.email] = {r.role for r in ExpenseRole.query.filter_by(email=user.email)}
    return cache[user.email]


def has_role(user, *roles) -> bool:
    return bool(roles_of(user) & set(roles))


def is_admin(user) -> bool:
    return user.is_super_admin


def can_setup(user) -> bool:
    """Shows, categories, vendors."""
    return is_admin(user) or has_role(user, VP_FINANCE)


def can_see_payments(user) -> bool:
    return is_admin(user) or has_role(user, *PAYERS)


def produces_any_show(user) -> bool:
    return (ExpenseShowProducer.query.join(ExpenseShow)
            .filter(ExpenseShowProducer.email == user.email, ExpenseShow.active.is_(True))
            .first() is not None)


def is_reviewer(user) -> bool:
    return has_role(user, *PAYERS) or produces_any_show(user)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _reviewers(emails) -> list[Reviewer]:
    emails = sorted(set(emails))
    names = {u.email: person_name(u) for u in User.query.filter(User.email.in_(emails))} if emails else {}
    return [Reviewer(e, names.get(e, e)) for e in emails]


def producers_for(claim) -> list[Reviewer]:
    if claim.show is None:
        return []
    return _reviewers(e for e in claim.show.producer_emails if e != claim.submitter.email)


def signer_role(claim) -> str:
    return PRESIDENT if has_role(claim.submitter, VP_FINANCE) else VP_FINANCE


def signers_for(claim) -> list[Reviewer]:
    emails = [r.email for r in ExpenseRole.query.filter_by(role=signer_role(claim))]
    return _reviewers(e for e in emails if e != claim.submitter.email)


def route(claim) -> str:
    """The status a claim enters when (re)submitted."""
    return SUBMITTED if producers_for(claim) else APPROVED


def waiting_on(claim) -> list[Reviewer]:
    if claim.status == SUBMITTED:
        return producers_for(claim)
    if claim.status == APPROVED:
        return signers_for(claim)
    return []


def can_review(user, claim) -> bool:
    return (user.id != claim.submitter_id
            and user.email in {r.email for r in waiting_on(claim)})


def review_queue(user) -> list:
    """Claims waiting on this user, oldest first."""
    claims = set(ExpenseClaim.query
                 .join(ExpenseShowProducer, ExpenseShowProducer.show_id == ExpenseClaim.show_id)
                 .filter(ExpenseClaim.status == SUBMITTED,
                         ExpenseShowProducer.email == user.email,
                         ExpenseClaim.submitter_id != user.id))
    if has_role(user, *PAYERS):
        for claim in ExpenseClaim.query.filter(ExpenseClaim.status == APPROVED,
                                               ExpenseClaim.submitter_id != user.id):
            if has_role(user, signer_role(claim)):
                claims.add(claim)
    return sorted(claims, key=lambda c: (c.submitted_at or c.created_at, c.id))


def can_pay(user, claim) -> bool:
    return claim.status == SIGNED_OFF and has_role(user, *PAYERS)


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------

def can_view(user, claim) -> bool:
    if claim.submitter_id == user.id:
        return claim.status != VOID or is_admin(user)
    if claim.status == DRAFT:
        return False                       # drafts are private to the submitter
    if is_admin(user) or has_role(user, *PAYERS):
        return True
    return claim.show is not None and user.email in claim.show.producer_emails
