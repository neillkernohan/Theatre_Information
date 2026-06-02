import os
from flask import render_template, redirect, url_for, flash, request, current_app
from werkzeug.utils import secure_filename
from inventory import inventory_bp
from inventory.models import db, InventoryItem, generate_item_code
from inventory.forms import InventoryItemForm
from auth.decorators import inventory_required

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}


def _save_image(file, item_id):
    """Save an uploaded image and return the relative static path."""
    ext = file.filename.rsplit('.', 1)[-1].lower()
    filename = secure_filename(f'item_{item_id}.{ext}')
    upload_dir = os.path.join(current_app.root_path, 'static', 'inventory', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, filename))
    return f'inventory/uploads/{filename}'


def _delete_image(image_path):
    """Delete an image file from disk if it exists."""
    if image_path:
        full_path = os.path.join(current_app.root_path, 'static', image_path)
        if os.path.exists(full_path):
            os.remove(full_path)


CATEGORY_LABELS = {
    'costume': 'Costume',
    'prop': 'Prop',
    'set_piece': 'Set Piece',
    'equipment': 'Equipment',
}

STATUS_LABELS = {
    'available': 'Available',
    'in_use': 'In Use',
    'needs_repair': 'Needs Repair',
    'retired': 'Retired',
}


@inventory_bp.route('/')
@inventory_required
def list_items():
    category_filter = request.args.get('category', '')
    status_filter = request.args.get('status', '')
    search = request.args.get('q', '').strip()

    query = InventoryItem.query

    if category_filter:
        query = query.filter_by(category=category_filter)
    if status_filter:
        query = query.filter_by(status=status_filter)
    if search:
        query = query.filter(
            db.or_(
                InventoryItem.name.ilike(f'%{search}%'),
                InventoryItem.item_code.ilike(f'%{search}%'),
                InventoryItem.storage_location.ilike(f'%{search}%'),
            )
        )

    items = query.order_by(InventoryItem.category, InventoryItem.name).all()

    return render_template(
        'inventory/list.html',
        items=items,
        category_filter=category_filter,
        status_filter=status_filter,
        search=search,
        category_labels=CATEGORY_LABELS,
        status_labels=STATUS_LABELS,
    )


@inventory_bp.route('/new', methods=['GET', 'POST'])
@inventory_required
def add_item():
    form = InventoryItemForm()

    if request.method == 'GET':
        default_category = request.args.get('category', 'costume')
        form.category.data = default_category
        form.item_code.data = generate_item_code(default_category)

    if form.validate_on_submit():
        if InventoryItem.query.filter_by(item_code=form.item_code.data.upper().strip()).first():
            flash(f'Item code "{form.item_code.data}" is already in use.', 'danger')
        else:
            item = InventoryItem(
                item_code=form.item_code.data.upper().strip(),
                name=form.name.data.strip(),
                category=form.category.data,
                quantity=form.quantity.data,
                storage_location=form.storage_location.data.strip() if form.storage_location.data else None,
                status=form.status.data,
                description=form.description.data.strip() if form.description.data else None,
                notes=form.notes.data.strip() if form.notes.data else None,
            )
            db.session.add(item)
            db.session.flush()  # get item.id before commit
            if form.image.data and form.image.data.filename:
                item.image_path = _save_image(form.image.data, item.id)
            db.session.commit()
            flash(f'Item "{item.name}" ({item.item_code}) added.', 'success')
            return redirect(url_for('inventory.list_items'))

    return render_template('inventory/form.html', form=form, editing=False)


@inventory_bp.route('/<int:item_id>/edit', methods=['GET', 'POST'])
@inventory_required
def edit_item(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    form = InventoryItemForm(obj=item)

    if form.validate_on_submit():
        new_code = form.item_code.data.upper().strip()
        conflict = InventoryItem.query.filter(
            InventoryItem.item_code == new_code,
            InventoryItem.id != item_id
        ).first()
        if conflict:
            flash(f'Item code "{new_code}" is already in use.', 'danger')
        else:
            item.item_code = new_code
            item.name = form.name.data.strip()
            item.category = form.category.data
            item.quantity = form.quantity.data
            item.storage_location = form.storage_location.data.strip() if form.storage_location.data else None
            item.status = form.status.data
            item.description = form.description.data.strip() if form.description.data else None
            item.notes = form.notes.data.strip() if form.notes.data else None
            if form.image.data and form.image.data.filename:
                _delete_image(item.image_path)
                item.image_path = _save_image(form.image.data, item.id)
            db.session.commit()
            flash(f'Item "{item.name}" updated.', 'success')
            return redirect(url_for('inventory.list_items'))

    return render_template('inventory/form.html', form=form, editing=True, item=item)


@inventory_bp.route('/<int:item_id>/delete', methods=['GET', 'POST'])
@inventory_required
def delete_item(item_id):
    item = InventoryItem.query.get_or_404(item_id)

    if request.method == 'POST':
        _delete_image(item.image_path)
        db.session.delete(item)
        db.session.commit()
        flash(f'Item "{item.name}" ({item.item_code}) deleted.', 'success')
        return redirect(url_for('inventory.list_items'))

    return render_template('inventory/delete.html', item=item)


@inventory_bp.route('/suggest-code')
@inventory_required
def suggest_code():
    """AJAX endpoint — returns a suggested item code for a given category."""
    from flask import jsonify
    category = request.args.get('category', 'costume')
    return jsonify({'code': generate_item_code(category)})
