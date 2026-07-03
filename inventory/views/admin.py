import os
from flask import render_template, redirect, url_for, flash, request, current_app
from werkzeug.utils import secure_filename
from inventory import inventory_bp
from inventory.models import db, InventoryItem, generate_item_code
from inventory.forms import InventoryItemForm
from auth.decorators import inventory_required

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}


MAX_IMAGE_DIMENSION = 1600


def _save_image(file, item_id):
    """Save an uploaded image, resized to a web-friendly size, and return the relative static path."""
    from PIL import Image

    ext = file.filename.rsplit('.', 1)[-1].lower()
    upload_dir = os.path.join(current_app.root_path, 'static', 'inventory', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)

    if ext == 'gif':
        # Don't recompress GIFs — resizing would drop animation frames
        filename = secure_filename(f'item_{item_id}.gif')
        file.save(os.path.join(upload_dir, filename))
        return f'inventory/uploads/{filename}'

    img = Image.open(file)
    # Apply EXIF rotation from phone cameras, then discard the tag
    from PIL import ImageOps
    img = ImageOps.exif_transpose(img)
    img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION))

    if ext in ('jpg', 'jpeg'):
        if img.mode != 'RGB':
            img = img.convert('RGB')
        filename = secure_filename(f'item_{item_id}.jpg')
        img.save(os.path.join(upload_dir, filename), 'JPEG', quality=85, optimize=True)
    else:
        filename = secure_filename(f'item_{item_id}.{ext}')
        img.save(os.path.join(upload_dir, filename))

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


@inventory_bp.route('/')
@inventory_required
def list_items():
    category_filter = request.args.get('category', '')
    status_filter = request.args.get('status', '')
    search = request.args.get('q', '').strip()

    query = InventoryItem.query

    if category_filter:
        query = query.filter_by(category=category_filter)
    if status_filter == 'available':
        query = query.filter(InventoryItem.qty_available > 0)
    elif status_filter == 'in_use':
        query = query.filter(InventoryItem.qty_in_use > 0)
    elif status_filter == 'needs_repair':
        query = query.filter(InventoryItem.qty_needs_repair > 0)
    elif status_filter == 'retired':
        query = query.filter(InventoryItem.qty_retired > 0)
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
                qty_available=form.qty_available.data,
                qty_in_use=form.qty_in_use.data,
                qty_needs_repair=form.qty_needs_repair.data,
                qty_retired=form.qty_retired.data,
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
            item.qty_available = form.qty_available.data
            item.qty_in_use = form.qty_in_use.data
            item.qty_needs_repair = form.qty_needs_repair.data
            item.qty_retired = form.qty_retired.data
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
