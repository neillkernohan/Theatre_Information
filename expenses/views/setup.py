"""Setup screens: shows & producers, categories, vendors, finance roles.

Shows, categories and vendors: super admins and the VP of Finance.
Finance roles: super admins only, so nobody can grant themselves a role.
"""
import re

from flask import flash, redirect, render_template, request, url_for

from auth.models import User, db
from expenses import expenses_bp
from expenses.models import (ROLES, ExpenseCategory, ExpenseRole, ExpenseShow,
                             ExpenseShowProducer, ExpenseVendor)
from expenses.views.common import admin_required, setup_required

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _clean(value):
    value = (value or '').strip()
    return value or None


def _email(value):
    value = (value or '').strip().lower()
    return value if EMAIL_RE.match(value) else None


def _checked(name) -> bool:
    return request.form.get(name) == 'true'


@expenses_bp.route('/setup')
@setup_required
def setup():
    return render_template('expenses/setup/index.html')


# ---------------------------------------------------------------------------
# Shows & producers
# ---------------------------------------------------------------------------

@expenses_bp.route('/setup/shows', methods=['GET', 'POST'])
@setup_required
def setup_shows():
    if request.method == 'POST':
        name, season = _clean(request.form.get('name')), _clean(request.form.get('season'))
        if not name or not season:
            flash('Name and season are required.', 'danger')
        elif ExpenseShow.query.filter_by(name=name, season=season).first():
            flash(f'{name} ({season}) already exists.', 'danger')
        else:
            show = ExpenseShow(name=name, season=season,
                               qb_class=_clean(request.form.get('qb_class')) or name)
            db.session.add(show)
            db.session.commit()
            return redirect(url_for('expenses.setup_show', show_id=show.id))
    shows = (ExpenseShow.query
             .order_by(ExpenseShow.active.desc(), ExpenseShow.season.desc(), ExpenseShow.name).all())
    return render_template('expenses/setup/shows.html', shows=shows)


@expenses_bp.route('/setup/shows/<int:show_id>', methods=['GET', 'POST'])
@setup_required
def setup_show(show_id):
    show = db.get_or_404(ExpenseShow, show_id)
    if request.method == 'POST':
        name, season = _clean(request.form.get('name')), _clean(request.form.get('season'))
        clash = (ExpenseShow.query.filter_by(name=name, season=season)
                 .filter(ExpenseShow.id != show.id).first())
        if not name or not season:
            flash('Name and season are required.', 'danger')
        elif clash:
            flash(f'{name} ({season}) already exists.', 'danger')
        else:
            show.name, show.season = name, season
            show.qb_class = _clean(request.form.get('qb_class'))
            show.active = _checked('active')
            db.session.commit()
            flash('Saved.', 'success')
        return redirect(url_for('expenses.setup_show', show_id=show.id))
    emails = show.producer_emails
    users = {u.email: u for u in User.query.filter(User.email.in_(emails))} if emails else {}
    return render_template('expenses/setup/show.html', show=show, users=users)


@expenses_bp.route('/setup/shows/<int:show_id>/producers', methods=['POST'])
@setup_required
def setup_producer_add(show_id):
    show = db.get_or_404(ExpenseShow, show_id)
    email = _email(request.form.get('email'))
    if email is None:
        flash('Enter a valid email address.', 'danger')
    elif email not in show.producer_emails:
        show.producers.append(ExpenseShowProducer(email=email))
        db.session.commit()
    return redirect(url_for('expenses.setup_show', show_id=show.id))


@expenses_bp.route('/setup/shows/<int:show_id>/producers/remove', methods=['POST'])
@setup_required
def setup_producer_remove(show_id):
    ExpenseShowProducer.query.filter_by(show_id=show_id,
                                        email=request.form.get('email', '')).delete()
    db.session.commit()
    return redirect(url_for('expenses.setup_show', show_id=show_id))


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@expenses_bp.route('/setup/categories', methods=['GET', 'POST'])
@setup_required
def setup_categories():
    if request.method == 'POST':
        label = _clean(request.form.get('label'))
        if not label:
            flash('Label is required.', 'danger')
        elif ExpenseCategory.query.filter_by(label=label).first():
            flash(f'“{label}” already exists.', 'danger')
        else:
            db.session.add(ExpenseCategory(label=label,
                                           qb_account=_clean(request.form.get('qb_account'))))
            db.session.commit()
        return redirect(url_for('expenses.setup_categories'))
    categories = (ExpenseCategory.query
                  .order_by(ExpenseCategory.active.desc(), ExpenseCategory.label).all())
    return render_template('expenses/setup/categories.html', categories=categories)


@expenses_bp.route('/setup/categories/<int:category_id>', methods=['POST'])
@setup_required
def setup_category(category_id):
    category = db.get_or_404(ExpenseCategory, category_id)
    label = _clean(request.form.get('label'))
    clash = (ExpenseCategory.query.filter_by(label=label)
             .filter(ExpenseCategory.id != category.id).first())
    if not label:
        flash('Label is required.', 'danger')
    elif clash:
        flash(f'“{label}” already exists.', 'danger')
    else:
        category.label = label
        category.qb_account = _clean(request.form.get('qb_account'))
        category.active = _checked('active')
        db.session.commit()
    return redirect(url_for('expenses.setup_categories'))


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

@expenses_bp.route('/setup/vendors')
@setup_required
def setup_vendors():
    vendors = ExpenseVendor.query.order_by(ExpenseVendor.active.desc(), ExpenseVendor.name).all()
    return render_template('expenses/setup/vendors.html', vendors=vendors)


@expenses_bp.route('/setup/vendors/new', methods=['GET', 'POST'], defaults={'vendor_id': None})
@expenses_bp.route('/setup/vendors/<int:vendor_id>', methods=['GET', 'POST'])
@setup_required
def setup_vendor(vendor_id):
    vendor = db.get_or_404(ExpenseVendor, vendor_id) if vendor_id else ExpenseVendor(active=True)
    if request.method == 'GET':
        return render_template('expenses/setup/vendor.html', vendor=vendor)

    values = {f: _clean(request.form.get(f)) for f in ('name', 'email', 'phone', 'address',
                                                       'hst_number')}
    error = None
    if not values['name']:
        error = 'Name is required.'
    elif values['email'] and _email(values['email']) is None:
        error = 'Enter a valid email address, or leave it blank.'
    elif (ExpenseVendor.query.filter_by(name=values['name'])
          .filter(ExpenseVendor.id != (vendor_id or 0)).first()):
        error = f'A vendor named “{values["name"]}” already exists.'
    if error:
        flash(error, 'danger')
        draft = ExpenseVendor(id=vendor_id, active=vendor.active, **values)
        return render_template('expenses/setup/vendor.html', vendor=draft), 400

    for field, value in values.items():
        setattr(vendor, field, value)
    vendor.active = _checked('active') if vendor_id else True
    if not vendor_id:
        db.session.add(vendor)
    db.session.commit()
    return redirect(url_for('expenses.setup_vendors'))


# ---------------------------------------------------------------------------
# Finance roles (super admin only)
# ---------------------------------------------------------------------------

@expenses_bp.route('/setup/roles', methods=['GET', 'POST'])
@admin_required
def setup_roles():
    if request.method == 'POST':
        email, role = _email(request.form.get('email')), request.form.get('role')
        if email is None or role not in ROLES:
            flash('Enter a valid email and choose a role.', 'danger')
        elif not ExpenseRole.query.filter_by(email=email, role=role).first():
            db.session.add(ExpenseRole(email=email, role=role))
            db.session.commit()
        return redirect(url_for('expenses.setup_roles'))
    roles = ExpenseRole.query.order_by(ExpenseRole.role, ExpenseRole.email).all()
    emails = [r.email for r in roles]
    users = {u.email: u for u in User.query.filter(User.email.in_(emails))} if emails else {}
    return render_template('expenses/setup/roles.html', roles=roles, users=users)


@expenses_bp.route('/setup/roles/<int:role_id>/remove', methods=['POST'])
@admin_required
def setup_role_remove(role_id):
    db.session.delete(db.get_or_404(ExpenseRole, role_id))
    db.session.commit()
    return redirect(url_for('expenses.setup_roles'))
