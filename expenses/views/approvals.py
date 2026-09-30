from flask import abort, render_template
from flask_login import current_user, login_required

from expenses import access, expenses_bp
from expenses.models import APPROVED, RETURNED, SIGNED_OFF, SUBMITTED, ExpenseClaim

IN_PROGRESS = [SUBMITTED, APPROVED, RETURNED, SIGNED_OFF]


@expenses_bp.route('/approvals')
@login_required
def approvals():
    oversees = access.is_admin(current_user) or access.has_role(current_user, *access.PAYERS)
    if not (oversees or access.is_reviewer(current_user)):
        abort(403)
    queue = access.review_queue(current_user)
    in_progress = []
    if oversees:
        claims = (ExpenseClaim.query.filter(ExpenseClaim.status.in_(IN_PROGRESS))
                  .order_by(ExpenseClaim.submitted_at).all())
        in_progress = [(c, access.waiting_on(c)) for c in claims if c not in queue]
    return render_template('expenses/approvals.html', queue=queue, in_progress=in_progress,
                           oversees=oversees)
