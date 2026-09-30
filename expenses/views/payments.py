"""Paying signed-off claims, and the QuickBooks export."""
from datetime import date, timedelta

from flask import Response, abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from auth.models import db
from expenses import access, export, expenses_bp, notify
from expenses.models import (CHEQUE, PAID, PAYMENT_METHODS, REIMBURSEMENT, SIGNED_OFF,
                             ExpenseCategory, ExpenseClaim, ExpensePayment)
from expenses.parsing import FormError, money, parse_date
from expenses.views.common import claim_page, log, payments_required, see_claim, viewable


def ready_to_pay() -> list:
    """Signed-off claims, invoices with the nearest due date first."""
    claims = ExpenseClaim.query.filter_by(status=SIGNED_OFF).all()

    def key(claim):
        signed = claim.last_event('signed off')
        return (claim.due_date or date.max, signed.created_at if signed else claim.created_at)
    return sorted(claims, key=key)


def _month_start(today: date) -> date:
    return today.replace(day=1)


@expenses_bp.route('/payments')
@payments_required
def payments():
    today = date.today()
    recent = (ExpenseClaim.query.join(ExpensePayment)
              .filter(ExpenseClaim.status == PAID,
                      ExpensePayment.paid_on >= today - timedelta(days=60))
              .order_by(ExpensePayment.paid_on.desc(), ExpenseClaim.id.desc()).all())
    unmapped = (ExpenseCategory.query
                .filter(ExpenseCategory.active.is_(True),
                        db.or_(ExpenseCategory.qb_account.is_(None),
                               ExpenseCategory.qb_account == ''))
                .order_by(ExpenseCategory.label).all())
    return render_template('expenses/payments.html', to_pay=ready_to_pay(), recent=recent,
                           today=today, unmapped=unmapped,
                           can_pay=access.has_role(current_user, *access.PAYERS),
                           export_start=_month_start(today).isoformat(),
                           export_end=today.isoformat())


@expenses_bp.route('/claims/<int:claim_id>/pay', methods=['POST'])
@login_required
def record_payment(claim_id):
    claim = viewable(claim_id)
    if not access.can_pay(current_user, claim):
        return claim_page(claim, "This claim isn't ready for you to pay. It may already be paid.",
                          409)
    method = request.form.get('method', '')
    reference = request.form.get('reference', '').strip()[:100] or None
    note = request.form.get('note', '').strip()[:500] or None
    try:
        if method not in PAYMENT_METHODS:
            raise FormError('Choose how it was paid.')
        when = parse_date(request.form.get('paid_on', ''), 'Payment date')
        if when > date.today():
            raise FormError("The payment date can't be in the future.")
        if method == CHEQUE and not reference:
            raise FormError('Enter the cheque number.')
    except FormError as exc:
        return claim_page(claim, str(exc), 400)

    claim.payment = ExpensePayment(method=method, paid_on=when, reference=reference, note=note,
                                   amount_cents=claim.total_cents, paid_by_id=current_user.id)
    claim.status = PAID
    detail = PAYMENT_METHODS[method] + (f' #{reference}' if reference else '')
    log(claim, 'paid it', f'{money(claim.total_cents)} by {detail} on {when}'
                          + (f' ({note})' if note else ''))
    db.session.commit()

    recipient = 'You were' if claim.kind == REIMBURSEMENT else f'{claim.payee_name} was'
    notify.to_submitter(claim, 'Paid', current_user, None,
                        f'{recipient} paid {money(claim.total_cents)} by {detail} on {when}.')
    return redirect(url_for('expenses.payments'))


@expenses_bp.route('/claims/<int:claim_id>/unpay', methods=['POST'])
@login_required
def undo_payment(claim_id):
    """Fix a payment recorded by mistake: back to 'signed off, to be paid'."""
    claim = viewable(claim_id)
    if claim.status != PAID or not access.has_role(current_user, *access.PAYERS):
        abort(403)
    reason = request.form.get('reason', '').strip()
    if not reason:
        return claim_page(claim, 'Say why the payment is being undone.', 400)
    claim.payment = None
    claim.status = SIGNED_OFF
    log(claim, 'undid the payment', reason)
    db.session.commit()
    return see_claim(claim)


@expenses_bp.route('/payments/export.csv')
@payments_required
def export_csv():
    status = request.args.get('status', PAID)
    if status == SIGNED_OFF:
        claims = ready_to_pay()
        filename = f'expenses-to-pay-{date.today()}.csv'
    elif status == PAID:
        try:
            first = (parse_date(request.args.get('start', ''), 'From', required=False)
                     or _month_start(date.today()))
            last = parse_date(request.args.get('end', ''), 'To', required=False) or date.today()
        except FormError as exc:
            abort(400, str(exc))
        claims = (ExpenseClaim.query.join(ExpensePayment)
                  .filter(ExpenseClaim.status == PAID, ExpensePayment.paid_on >= first,
                          ExpensePayment.paid_on <= last)
                  .order_by(ExpensePayment.paid_on, ExpenseClaim.id).all())
        filename = f'expenses-paid-{first}-to-{last}.csv'
    else:
        abort(400, 'Unknown status.')
    return Response(export.to_csv(claims), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})
