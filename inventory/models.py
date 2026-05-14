from auth.models import db
from datetime import datetime


CATEGORY_PREFIXES = {
    'costume': 'COST',
    'prop': 'PROP',
    'set_piece': 'SET',
    'equipment': 'EQUIP',
}


def generate_item_code(category):
    prefix = CATEGORY_PREFIXES.get(category, 'ITEM')
    existing = InventoryItem.query.filter_by(category=category).count()
    return f"{prefix}-{existing + 1:04d}"


class InventoryItem(db.Model):
    __tablename__ = 'inventory_items'
    __bind_key__ = 'inventory'

    id = db.Column(db.Integer, primary_key=True)
    item_code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    category = db.Column(
        db.Enum('costume', 'prop', 'set_piece', 'equipment', name='inv_category'),
        nullable=False
    )
    quantity = db.Column(db.Integer, nullable=False, default=1)
    storage_location = db.Column(db.String(255))
    status = db.Column(
        db.Enum('available', 'in_use', 'needs_repair', 'retired', name='inv_status'),
        nullable=False,
        default='available'
    )
    description = db.Column(db.Text)
    notes = db.Column(db.Text)
    image_path = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<InventoryItem {self.item_code} {self.name}>'
