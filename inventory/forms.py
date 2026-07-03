from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, SelectField, IntegerField, TextAreaField, SubmitField, ValidationError
from wtforms.validators import DataRequired, Length, Optional, NumberRange


class InventoryItemForm(FlaskForm):
    item_code = StringField('Item Code', validators=[DataRequired(), Length(max=20)])
    name = StringField('Name', validators=[DataRequired(), Length(max=255)])
    category = SelectField('Category', choices=[
        ('costume', 'Costume'),
        ('prop', 'Prop'),
        ('set_piece', 'Set Piece'),
        ('equipment', 'Equipment'),
    ], validators=[DataRequired()])
    quantity = IntegerField('Total Quantity', validators=[DataRequired(), NumberRange(min=1)], default=1)
    storage_location = StringField('Storage Location', validators=[Optional(), Length(max=255)])
    qty_available = IntegerField('Available', validators=[DataRequired(), NumberRange(min=0)], default=0)
    qty_in_use = IntegerField('In Use', validators=[DataRequired(), NumberRange(min=0)], default=0)
    qty_needs_repair = IntegerField('Needs Repair', validators=[DataRequired(), NumberRange(min=0)], default=0)
    qty_retired = IntegerField('Retired', validators=[DataRequired(), NumberRange(min=0)], default=0)
    description = TextAreaField('Description', validators=[Optional()])
    notes = TextAreaField('Notes', validators=[Optional()])
    image = FileField('Photo', validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], 'Images only.')])
    submit = SubmitField('Save')

    def validate_qty_available(self, field):
        total = (field.data or 0) + (self.qty_in_use.data or 0) + (self.qty_needs_repair.data or 0) + (self.qty_retired.data or 0)
        if total != (self.quantity.data or 0):
            raise ValidationError(f'Status quantities must add up to total quantity ({self.quantity.data}).')
