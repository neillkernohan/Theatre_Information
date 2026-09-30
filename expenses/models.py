"""Expense claims: reimbursements and vendor invoices.

Lives in the main database (next to ``users``) so claims link to the people
who submit, approve and pay them. Expense roles and show producers are keyed
by email rather than user id, so they can be assigned before someone has ever
signed in; ``users.email`` is unique and lower-cased, so it's a safe key.
"""
from datetime import datetime

from auth.models import db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VP_FINANCE = 'vp_finance'
PRESIDENT = 'president'
ROLES = {VP_FINANCE: 'VP of Finance', PRESIDENT: 'President'}

REIMBURSEMENT = 'reimbursement'
INVOICE = 'invoice'
KINDS = {REIMBURSEMENT: 'Reimbursement', INVOICE: 'Vendor invoice'}

DRAFT = 'draft'
SUBMITTED = 'submitted'      # waiting for a show producer
RETURNED = 'returned'        # sent back to the submitter for changes
APPROVED = 'approved'        # waiting for sign-off
SIGNED_OFF = 'signed_off'    # ready to pay
PAID = 'paid'
REJECTED = 'rejected'
VOID = 'void'
STATUSES = {
    DRAFT: 'Draft',
    SUBMITTED: 'Waiting for producer',
    RETURNED: 'Returned for changes',
    APPROVED: 'Waiting for sign-off',
    SIGNED_OFF: 'Signed off, to be paid',
    PAID: 'Paid',
    REJECTED: 'Rejected',
    VOID: 'Void',
}
EDITABLE = {DRAFT, RETURNED}

ETRANSFER = 'etransfer'
CHEQUE = 'cheque'
OTHER = 'other'
PAYMENT_METHODS = {ETRANSFER: 'Interac e-Transfer', CHEQUE: 'Cheque', OTHER: 'Other (EFT, cash…)'}


def person_name(user) -> str:
    """'First Last', falling back to the email address."""
    if user is None:
        return '—'
    name = f'{user.first_name or ""} {user.last_name or ""}'.strip()
    return name if name and name != 'Unknown' else user.email


# ---------------------------------------------------------------------------
# Setup: roles, shows, categories, vendors, profiles
# ---------------------------------------------------------------------------

class ExpenseRole(db.Model):
    """VP of Finance / President. (Expenses admin = the site's super admin.)"""
    __tablename__ = 'expense_roles'
    __table_args__ = (db.UniqueConstraint('email', 'role'),)

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)


class ExpenseShow(db.Model):
    """A production. Its QuickBooks class tags every expense booked to it."""
    __tablename__ = 'expense_shows'
    __table_args__ = (db.UniqueConstraint('name', 'season'),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    season = db.Column(db.String(20), nullable=False)          # e.g. "2026-27"
    qb_class = db.Column(db.String(255))
    active = db.Column(db.Boolean, nullable=False, default=True)

    producers = db.relationship('ExpenseShowProducer', cascade='all, delete-orphan',
                                order_by='ExpenseShowProducer.email')

    @property
    def producer_emails(self) -> list[str]:
        return [p.email for p in self.producers]


class ExpenseShowProducer(db.Model):
    """Someone who approves a show's expenses. Any one producer suffices."""
    __tablename__ = 'expense_show_producers'

    show_id = db.Column(db.Integer, db.ForeignKey('expense_shows.id'), primary_key=True)
    email = db.Column(db.String(255), primary_key=True)


class ExpenseCategory(db.Model):
    """A plain-language category mapped to a QuickBooks account."""
    __tablename__ = 'expense_categories'

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(255), unique=True, nullable=False)
    qb_account = db.Column(db.String(255))
    active = db.Column(db.Boolean, nullable=False, default=True)


class ExpenseVendor(db.Model):
    """A business that invoices the theatre directly."""
    __tablename__ = 'expense_vendors'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(50))
    address = db.Column(db.String(1024))
    hst_number = db.Column(db.String(50))
    active = db.Column(db.Boolean, nullable=False, default=True)


class ExpenseProfile(db.Model):
    """Where to send someone's reimbursements, if not their login email."""
    __tablename__ = 'expense_profiles'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    etransfer_email = db.Column(db.String(255))


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

class ExpenseClaim(db.Model):
    """A reimbursement (payee: the submitter) or vendor invoice (payee: vendor).
    One claim is for one show, or general operations when ``show_id`` is NULL."""
    __tablename__ = 'expense_claims'

    id = db.Column(db.Integer, primary_key=True)
    submitter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False, default=REIMBURSEMENT)
    show_id = db.Column(db.Integer, db.ForeignKey('expense_shows.id'), index=True)
    title = db.Column(db.String(255), nullable=False)

    # Vendor invoices only. vendor_other: a name typed by the submitter when
    # the vendor isn't set up yet.
    vendor_id = db.Column(db.Integer, db.ForeignKey('expense_vendors.id'))
    vendor_other = db.Column(db.String(255))
    invoice_number = db.Column(db.String(100))
    invoice_date = db.Column(db.Date)
    due_date = db.Column(db.Date)

    status = db.Column(db.String(20), nullable=False, default=DRAFT, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)
    submitted_at = db.Column(db.DateTime)

    submitter = db.relationship('User')
    show = db.relationship('ExpenseShow')
    vendor = db.relationship('ExpenseVendor')
    lines = db.relationship('ExpenseLine', back_populates='claim', cascade='all, delete-orphan',
                            order_by='(ExpenseLine.spent_on, ExpenseLine.id)')
    attachments = db.relationship('ExpenseAttachment', back_populates='claim',
                                  cascade='all, delete-orphan', order_by='ExpenseAttachment.id')
    events = db.relationship('ExpenseEvent', back_populates='claim',
                             cascade='all, delete-orphan', order_by='ExpenseEvent.id')
    payment = db.relationship('ExpensePayment', back_populates='claim', uselist=False,
                              cascade='all, delete-orphan')

    @property
    def total_cents(self) -> int:
        return sum(line.total_cents for line in self.lines)

    @property
    def hst_cents(self) -> int:
        return sum(line.hst_cents for line in self.lines)

    @property
    def is_editable(self) -> bool:
        return self.status in EDITABLE

    @property
    def claim_files(self):
        """Documents attached to the claim as a whole (e.g. the invoice PDF)."""
        return [a for a in self.attachments if a.line_id is None]

    def last_event(self, action):
        return next((e for e in reversed(self.events) if e.action == action), None)

    @property
    def payee_name(self) -> str:
        if self.kind == INVOICE:
            return self.vendor.name if self.vendor else (self.vendor_other or '—')
        return person_name(self.submitter)

    @property
    def payee_email(self):
        """Where to send an e-Transfer."""
        if self.kind == INVOICE:
            return self.vendor.email if self.vendor else None
        profile = db.session.get(ExpenseProfile, self.submitter_id)
        return (profile.etransfer_email if profile and profile.etransfer_email
                else self.submitter.email)


class ExpenseLine(db.Model):
    """One receipt / expense. ``total_cents`` includes HST."""
    __tablename__ = 'expense_lines'

    id = db.Column(db.Integer, primary_key=True)
    claim_id = db.Column(db.Integer, db.ForeignKey('expense_claims.id'), nullable=False, index=True)
    spent_on = db.Column(db.Date, nullable=False)
    merchant = db.Column(db.String(255))
    description = db.Column(db.String(500), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('expense_categories.id'), nullable=False)
    total_cents = db.Column(db.Integer, nullable=False)
    hst_cents = db.Column(db.Integer, nullable=False, default=0)

    claim = db.relationship('ExpenseClaim', back_populates='lines')
    category = db.relationship('ExpenseCategory')
    attachments = db.relationship('ExpenseAttachment', back_populates='line',
                                  order_by='ExpenseAttachment.id')

    @property
    def subtotal_cents(self) -> int:
        return self.total_cents - self.hst_cents


class ExpenseAttachment(db.Model):
    """An uploaded receipt or invoice. Files live on disk, outside static/."""
    __tablename__ = 'expense_attachments'

    id = db.Column(db.Integer, primary_key=True)
    claim_id = db.Column(db.Integer, db.ForeignKey('expense_claims.id'), nullable=False, index=True)
    line_id = db.Column(db.Integer, db.ForeignKey('expense_lines.id'), index=True)
    stored_name = db.Column(db.String(100), unique=True, nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    claim = db.relationship('ExpenseClaim', back_populates='attachments')
    line = db.relationship('ExpenseLine', back_populates='attachments')


class ExpenseEvent(db.Model):
    """Audit trail: who did what to a claim, and when."""
    __tablename__ = 'expense_events'

    id = db.Column(db.Integer, primary_key=True)
    claim_id = db.Column(db.Integer, db.ForeignKey('expense_claims.id'), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    claim = db.relationship('ExpenseClaim', back_populates='events')
    actor = db.relationship('User')


class ExpensePayment(db.Model):
    """How and when a signed-off claim was paid. One per claim."""
    __tablename__ = 'expense_payments'

    id = db.Column(db.Integer, primary_key=True)
    claim_id = db.Column(db.Integer, db.ForeignKey('expense_claims.id'), unique=True, nullable=False)
    method = db.Column(db.String(20), nullable=False)
    reference = db.Column(db.String(100))
    paid_on = db.Column(db.Date, nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(500))
    paid_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    claim = db.relationship('ExpenseClaim', back_populates='payment')
    paid_by = db.relationship('User')
