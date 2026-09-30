"""Helpers shared by the expense views."""
from datetime import date
from functools import wraps

from flask import abort, redirect, render_template, url_for
from flask_login import current_user, login_required

from auth.models import db
from expenses import access, expenses_bp
from expenses.models import (INVOICE, KINDS, PAYMENT_METHODS, REIMBURSEMENT, ROLES, STATUSES,
                             ExpenseCategory, ExpenseClaim, ExpenseEvent, ExpenseShow,
                             ExpenseVendor, person_name)
from expenses.parsing import local_time, money


@expenses_bp.context_processor
def _template_helpers():
    """Available in every expenses template."""
    if not current_user.is_authenticated:
        return {}
    return {
        'KINDS': KINDS, 'STATUSES': STATUSES, 'ROLES': ROLES, 'PAYMENT_METHODS': PAYMENT_METHODS,
        'money': money, 'local_time': local_time, 'person_name': person_name,
        'nav': {
            'approvals': access.is_reviewer(current_user) or access.is_admin(current_user),
            'payments': access.can_see_payments(current_user),
            'setup': access.can_setup(current_user),
        },
    }


# ---------------------------------------------------------------------------
# Access decorators
# ---------------------------------------------------------------------------

def _requires(check):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not check(current_user):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


setup_required = _requires(access.can_setup)
admin_required = _requires(access.is_admin)
payments_required = _requires(access.can_see_payments)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

def load_claim(claim_id) -> ExpenseClaim:
    return db.get_or_404(ExpenseClaim, claim_id)


def viewable(claim_id) -> ExpenseClaim:
    claim = load_claim(claim_id)
    if not access.can_view(current_user, claim):
        abort(403)
    return claim


def editable(claim_id) -> ExpenseClaim:
    """The claim, if the current user may change it right now."""
    claim = load_claim(claim_id)
    if claim.submitter_id != current_user.id:
        abort(403)
    if not claim.is_editable:
        abort(409, "This claim can't be changed now.")
    return claim


def log(claim, action, comment=None):
    claim.events.append(ExpenseEvent(actor_id=current_user.id, action=action, comment=comment))


def see_claim(claim, anchor=None):
    return redirect(url_for('expenses.claim_detail', claim_id=claim.id, _anchor=anchor))


def options(claim=None) -> dict:
    """Choices for show / category / vendor dropdowns."""
    shows = (ExpenseShow.query.filter_by(active=True)
             .order_by(ExpenseShow.season.desc(), ExpenseShow.name).all())
    categories = ExpenseCategory.query.filter_by(active=True).order_by(ExpenseCategory.label).all()
    vendors = ExpenseVendor.query.filter_by(active=True).order_by(ExpenseVendor.name).all()
    if claim is not None:                  # keep a since-deactivated choice selectable
        if claim.show and claim.show not in shows:
            shows.append(claim.show)
        if claim.vendor and claim.vendor not in vendors:
            vendors.append(claim.vendor)
    return {'shows': shows, 'categories': categories, 'vendors': vendors}


def duplicate_invoices(claim) -> list:
    """Other live claims for the same vendor and invoice number."""
    from expenses.models import DRAFT, REJECTED, VOID
    if claim.kind != INVOICE or not claim.invoice_number:
        return []
    q = ExpenseClaim.query.filter(
        ExpenseClaim.id != claim.id, ExpenseClaim.kind == INVOICE,
        ExpenseClaim.status.notin_([DRAFT, VOID, REJECTED]),
        db.func.lower(ExpenseClaim.invoice_number) == claim.invoice_number.lower())
    if claim.vendor_id:
        q = q.filter(ExpenseClaim.vendor_id == claim.vendor_id)
    elif claim.vendor_other:
        q = q.filter(db.func.lower(ExpenseClaim.vendor_other) == claim.vendor_other.lower())
    else:
        return []
    return q.all()


def submission_problems(claim) -> list[str]:
    problems = []
    if not claim.lines:
        problems.append('Add at least one expense line.')
    if claim.show is not None and not claim.show.active:
        problems.append(f'{claim.show.name} is no longer taking claims. '
                        'Choose another show or General.')
    if claim.kind == REIMBURSEMENT:
        missing = [line for line in claim.lines if not line.attachments]
        if missing:
            problems.append(f'{len(missing)} line(s) still need a receipt photo.')
    else:
        if not (claim.vendor or claim.vendor_other):
            problems.append('Choose the vendor (or type its name under Other).')
        if not claim.invoice_number:
            problems.append('Enter the invoice number.')
        if not claim.attachments:
            problems.append('Attach a copy of the invoice.')
    return problems


def claim_page(claim, error=None, status=200, line_form=None):
    can_edit = claim.submitter_id == current_user.id and claim.is_editable
    return render_template(
        'expenses/claim.html', claim=claim, can_edit=can_edit, error=error,
        can_review=access.can_review(current_user, claim),
        can_pay=access.can_pay(current_user, claim),
        can_undo_payment=access.has_role(current_user, *access.PAYERS),
        waiting_on=access.waiting_on(claim),
        problems=submission_problems(claim) if can_edit else [],
        duplicates=duplicate_invoices(claim),
        line_form=line_form or {}, today=date.today().isoformat(),
        **options(claim),
    ), status
