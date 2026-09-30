from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from auth.models import db
from expenses import access, expenses_bp
from expenses.models import (SIGNED_OFF, ExpenseClaim, ExpenseProfile, ExpenseShow,
                             ExpenseShowProducer)


@expenses_bp.route('/')
@login_required
def index():
    claims = (ExpenseClaim.query.filter_by(submitter_id=current_user.id)
              .order_by(ExpenseClaim.created_at.desc()).all())
    producing = (ExpenseShow.query.join(ExpenseShowProducer)
                 .filter(ExpenseShowProducer.email == current_user.email,
                         ExpenseShow.active.is_(True))
                 .order_by(ExpenseShow.season.desc(), ExpenseShow.name).all())
    to_pay = (ExpenseClaim.query.filter_by(status=SIGNED_OFF).count()
              if access.has_role(current_user, *access.PAYERS) else 0)
    return render_template('expenses/index.html', claims=claims, producing=producing,
                           waiting=len(access.review_queue(current_user)), to_pay=to_pay)


@expenses_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Where reimbursements are e-Transferred (name/phone live on the main account)."""
    record = db.session.get(ExpenseProfile, current_user.id)
    if request.method == 'POST':
        if record is None:
            record = ExpenseProfile(user_id=current_user.id)
            db.session.add(record)
        record.etransfer_email = request.form.get('etransfer_email', '').strip().lower() or None
        db.session.commit()
        flash('Saved.', 'success')
        return redirect(url_for('expenses.index'))
    return render_template('expenses/profile.html', record=record)
