"""Creating, editing, submitting and reviewing claims; serving their files."""
from datetime import date, datetime

from flask import abort, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from auth.models import db
from expenses import access, ai, expenses_bp, notify, storage
from expenses.models import (APPROVED, DRAFT, INVOICE, KINDS, REIMBURSEMENT, REJECTED, RETURNED,
                             SIGNED_OFF, SUBMITTED, ExpenseAttachment, ExpenseCategory,
                             ExpenseClaim, ExpenseLine, ExpenseShow, ExpenseVendor, person_name)
from expenses.parsing import FormError, parse_date, parse_money
from expenses.views.common import (claim_page, editable, load_claim, log, options, see_claim,
                                   submission_problems, viewable)

HEADER_FIELDS = ('show_id', 'title', 'vendor', 'vendor_other', 'invoice_number',
                 'invoice_date', 'due_date')
LINE_FIELDS = ('spent_on', 'merchant', 'description', 'category_id', 'total', 'hst')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _form(fields) -> dict:
    return {f: request.form.get(f, '') for f in fields}


def _real_files(name):
    # Browsers send an empty part when no file was chosen.
    return [f for f in request.files.getlist(name) if f and f.filename]


def _store_files(claim, uploads, line=None):
    """Save uploads and attach them; on any bad file, keep none of them."""
    saved = []
    try:
        for upload in uploads:
            stored, content_type, size = storage.save(upload)
            saved.append((stored, content_type, size, upload.filename or 'file'))
    except storage.UploadError:
        for stored, *_ in saved:
            storage.delete(stored)
        raise
    for stored, content_type, size, original in saved:
        claim.attachments.append(ExpenseAttachment(
            line=line, stored_name=stored, original_name=original[:255],
            content_type=content_type, size_bytes=size, uploaded_by=current_user.id))


def _apply_header(claim, f):
    title = f['title'].strip()
    if not title:
        raise FormError('Say briefly what this claim is for.')
    claim.title = title[:255]

    show_id = f['show_id']
    if show_id:
        show = db.session.get(ExpenseShow, int(show_id)) if show_id.isdigit() else None
        if show is None or (not show.active and show.id != claim.show_id):
            raise FormError('Choose a current show, or General.')
        claim.show = show
    else:
        claim.show = None

    if claim.kind != INVOICE:
        return
    vendor = f['vendor']
    if vendor == 'other':
        claim.vendor, claim.vendor_other = None, f['vendor_other'].strip() or None
    elif vendor.isdigit() and (v := db.session.get(ExpenseVendor, int(vendor))) is not None:
        claim.vendor, claim.vendor_other = v, None
    else:
        claim.vendor, claim.vendor_other = None, None
    claim.invoice_number = f['invoice_number'].strip() or None
    claim.invoice_date = parse_date(f['invoice_date'], 'Invoice date', required=False)
    claim.due_date = parse_date(f['due_date'], 'Due date', required=False)


def _line_values(claim, f) -> dict:
    values = {
        'spent_on': parse_date(f['spent_on'], 'Date'),
        'merchant': f['merchant'].strip()[:255] or None,
        'description': f['description'].strip()[:500],
        # Negative amounts are refunds/returns; HST then follows the total's sign.
        'total_cents': parse_money(f['total'], 'Total', allow_negative=True),
        'hst_cents': parse_money(f['hst'], 'HST', allow_zero=True, allow_negative=True),
    }
    if values['spent_on'] > date.today():
        raise FormError("The date can't be in the future.")
    if not values['description']:
        raise FormError('Describe what was bought.')
    total, hst = values['total_cents'], values['hst_cents']
    if hst and (hst < 0) != (total < 0):
        raise FormError('For a refund, enter the HST as a negative amount too.'
                        if total < 0 else "HST can't be negative on a purchase.")
    if abs(hst) > abs(total):
        raise FormError("HST can't be more than the total.")
    cid = f['category_id']
    category = db.session.get(ExpenseCategory, int(cid)) if cid.isdigit() else None
    if category is None:
        raise FormError('Choose a category.')
    values['category'] = category
    if claim.kind == REIMBURSEMENT and not values['merchant']:
        raise FormError('Enter where it was bought.')
    return values


def _line(claim, line_id) -> ExpenseLine:
    line = next((l for l in claim.lines if l.id == line_id), None)
    if line is None:
        abort(404)
    return line


# ---------------------------------------------------------------------------
# New claim
# ---------------------------------------------------------------------------

@expenses_bp.route('/claims/new', methods=['GET', 'POST'])
@login_required
def new_claim():
    kind = request.values.get('kind', REIMBURSEMENT)
    kind = kind if kind in KINDS else REIMBURSEMENT
    if request.method == 'GET':
        return render_template('expenses/new.html', form={'kind': kind}, **options())

    f = _form(HEADER_FIELDS)
    claim = ExpenseClaim(submitter_id=current_user.id, kind=kind, status=DRAFT)
    try:
        _apply_header(claim, f)
    except FormError as exc:
        db.session.rollback()
        return render_template('expenses/new.html', form={'kind': kind, **f}, error=str(exc),
                               **options()), 400
    db.session.add(claim)
    log(claim, 'created')
    db.session.commit()
    return see_claim(claim)


# ---------------------------------------------------------------------------
# View / edit
# ---------------------------------------------------------------------------

@expenses_bp.route('/claims/<int:claim_id>')
@login_required
def claim_detail(claim_id):
    return claim_page(viewable(claim_id))


@expenses_bp.route('/claims/<int:claim_id>', methods=['POST'])
@login_required
def claim_update(claim_id):
    claim = editable(claim_id)
    try:
        _apply_header(claim, _form(HEADER_FIELDS))
    except FormError as exc:
        db.session.rollback()
        return claim_page(load_claim(claim_id), str(exc), 400)
    db.session.commit()
    return see_claim(claim)


@expenses_bp.route('/claims/<int:claim_id>/lines', methods=['POST'])
@login_required
def line_add(claim_id):
    claim = editable(claim_id)
    f = _form(LINE_FIELDS)
    receipts = _real_files('receipts')
    try:
        if len(receipts) > 1:
            raise FormError('Attach one receipt per expense. Add each receipt as its own line.')
        line = ExpenseLine(**_line_values(claim, f))
        claim.lines.append(line)
        _store_files(claim, receipts, line)
    except (FormError, storage.UploadError) as exc:
        db.session.rollback()
        return claim_page(load_claim(claim_id), str(exc), 400, line_form=f)
    db.session.commit()
    return see_claim(claim, 'lines')


@expenses_bp.route('/claims/<int:claim_id>/lines/<int:line_id>', methods=['POST'])
@login_required
def line_update(claim_id, line_id):
    claim = editable(claim_id)
    line = _line(claim, line_id)
    try:
        for field, value in _line_values(claim, _form(LINE_FIELDS)).items():
            setattr(line, field, value)
    except FormError as exc:
        db.session.rollback()
        return claim_page(load_claim(claim_id), str(exc), 400)
    db.session.commit()
    return see_claim(claim, 'lines')


@expenses_bp.route('/claims/<int:claim_id>/lines/<int:line_id>/delete', methods=['POST'])
@login_required
def line_delete(claim_id, line_id):
    claim = editable(claim_id)
    line = _line(claim, line_id)
    stored = [a.stored_name for a in line.attachments]
    for attachment in list(line.attachments):
        claim.attachments.remove(attachment)
    claim.lines.remove(line)
    db.session.commit()
    for name in stored:
        storage.delete(name)
    return see_claim(claim, 'lines')


@expenses_bp.route('/claims/<int:claim_id>/files', methods=['POST'])
@login_required
def files_add(claim_id):
    """Attach the receipt for a line (``line_id``) or the claim's invoice.
    One file each: to replace it, remove the old one first."""
    claim = editable(claim_id)
    line = None
    line_id = request.form.get('line_id', '')
    if line_id:
        line = next((l for l in claim.lines if str(l.id) == line_id), None)
        if line is None:
            abort(404)
    uploads = _real_files('files')
    if not uploads:
        return claim_page(claim, 'Choose a file to upload.', 400)
    if len(uploads) > 1:
        return claim_page(claim, 'Upload one file at a time.', 400)
    existing = line.attachments if line else claim.claim_files
    if existing:
        what = 'receipt' if line else 'invoice'
        return claim_page(claim, f'This already has its {what}. Remove it first to replace it.', 400)
    try:
        _store_files(claim, uploads, line)
    except storage.UploadError as exc:
        db.session.rollback()
        return claim_page(load_claim(claim_id), str(exc), 400)
    db.session.commit()
    if line is None and ai.available():
        # Read the new invoice straight away (the page runs it on load).
        new = claim.claim_files[-1]
        return redirect(url_for('expenses.claim_detail', claim_id=claim.id,
                                read=new.id, _anchor='files'))
    return see_claim(claim, 'lines' if line else 'files')


@expenses_bp.route('/claims/<int:claim_id>/files/<int:attachment_id>/delete', methods=['POST'])
@login_required
def file_delete(claim_id, attachment_id):
    claim = editable(claim_id)
    attachment = next((a for a in claim.attachments if a.id == attachment_id), None)
    if attachment is None:
        abort(404)
    claim.attachments.remove(attachment)
    db.session.commit()
    storage.delete(attachment.stored_name)
    return see_claim(claim)


@expenses_bp.route('/claims/<int:claim_id>/delete', methods=['POST'])
@login_required
def claim_delete(claim_id):
    claim = editable(claim_id)
    if claim.status != DRAFT:
        abort(409, 'Only drafts can be deleted.')
    stored = [a.stored_name for a in claim.attachments]
    db.session.delete(claim)
    db.session.commit()
    for name in stored:
        storage.delete(name)
    return redirect(url_for('expenses.index'))


# ---------------------------------------------------------------------------
# Submit & review
# ---------------------------------------------------------------------------

@expenses_bp.route('/claims/<int:claim_id>/submit', methods=['POST'])
@login_required
def claim_submit(claim_id):
    claim = editable(claim_id)
    if submission_problems(claim):
        return claim_page(claim, "This claim isn't ready to submit yet.", 400)
    resubmitting = claim.status == RETURNED
    claim.status = access.route(claim)
    claim.submitted_at = datetime.utcnow()

    note = None
    if claim.show and claim.status == APPROVED and current_user.email not in claim.show.producer_emails:
        note = f'{claim.show.name} has no producer set up, so it went straight to sign-off.'
    log(claim, 'resubmitted' if resubmitting else 'submitted', note)
    db.session.commit()

    step = 'approve' if claim.status == SUBMITTED else 'sign off'
    notify.needs_review(claim, access.waiting_on(claim), step)
    return see_claim(claim)


@expenses_bp.route('/claims/<int:claim_id>/review', methods=['POST'])
@login_required
def claim_review(claim_id):
    """A producer approves, or a VP of Finance / President signs off — or
    either returns the claim for changes or rejects it."""
    claim = viewable(claim_id)
    if not access.can_review(current_user, claim):
        return claim_page(claim, "This claim isn't waiting for you. "
                                 "Someone may already have acted on it.", 409)
    decision = request.form.get('decision', '')
    comment = request.form.get('comment', '').strip() or None
    if decision in ('return', 'reject') and not comment:
        return claim_page(claim, 'Please say why, so the submitter knows what to do.', 400)
    if decision not in ('approve', 'return', 'reject'):
        abort(400)

    if decision == 'approve' and claim.status == SUBMITTED:
        claim.status = APPROVED
        log(claim, 'approved', comment)
        db.session.commit()
        notify.needs_review(claim, access.signers_for(claim), 'sign off')
    elif decision == 'approve':
        claim.status = SIGNED_OFF
        log(claim, 'signed off', comment)
        db.session.commit()
        who = 'you' if claim.kind == REIMBURSEMENT else 'the vendor'
        notify.to_submitter(claim, 'Signed off', current_user, comment,
                            f"It's ready to be paid; {who} will be paid soon.")
    elif decision == 'return':
        claim.status = RETURNED
        log(claim, 'returned it', comment)
        db.session.commit()
        notify.to_submitter(claim, 'Returned', current_user, comment,
                            'Please make the changes and submit it again.')
    else:
        claim.status = REJECTED
        log(claim, 'rejected it', comment)
        db.session.commit()
        notify.to_submitter(claim, 'Rejected', current_user, comment,
                            f"It won't be paid. Questions? Contact {person_name(current_user)} "
                            f'at {current_user.email}.')
    return redirect(url_for('expenses.approvals'))


# ---------------------------------------------------------------------------
# Read a receipt / invoice with AI (pre-fills the forms; nothing is saved)
# ---------------------------------------------------------------------------

@expenses_bp.route('/claims/<int:claim_id>/extract', methods=['POST'])
@login_required
def claim_extract(claim_id):
    """Suggest form values from a new photo (``file``) or an attached file
    (``attachment_id``). Only the claim's owner, while it's editable."""
    if not ai.available():
        abort(404)
    claim = editable(claim_id)

    attachment_id = request.form.get('attachment_id', '')
    try:
        if attachment_id:
            attachment = next((a for a in claim.attachments if str(a.id) == attachment_id), None)
            if attachment is None:
                abort(404)
            data = storage.path_for(attachment.stored_name).read_bytes()
            content_type = attachment.content_type
        else:
            upload = request.files.get('file')
            if not upload or not upload.filename:
                return jsonify(error='Choose a photo or PDF first.'), 400
            data, content_type = storage.read_valid(upload)
    except storage.UploadError as exc:
        return jsonify(error=str(exc)), 400

    categories = ExpenseCategory.query.filter_by(active=True).all()
    try:
        fields = ai.extract(data, content_type, [c.label for c in categories])
    except ai.ExtractionError as exc:
        return jsonify(error=str(exc)), 422

    by_label = {c.label: c.id for c in categories}
    fields['category_id'] = by_label.get(fields['category'])
    if claim.kind == INVOICE and fields['merchant']:
        vendor = (ExpenseVendor.query.filter_by(active=True)
                  .filter(db.func.lower(ExpenseVendor.name) == fields['merchant'].lower()).first())
        fields['vendor_id'] = vendor.id if vendor else None
    return jsonify(fields)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

@expenses_bp.route('/files/<int:attachment_id>')
@login_required
def file_download(attachment_id):
    attachment = db.get_or_404(ExpenseAttachment, attachment_id)
    if not access.can_view(current_user, attachment.claim):
        abort(403)
    path = storage.path_for(attachment.stored_name)
    if not path.exists():
        abort(404)
    response = send_file(path, mimetype=attachment.content_type, as_attachment=False,
                         download_name=attachment.original_name, max_age=3600)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.cache_control.private = True
    return response
