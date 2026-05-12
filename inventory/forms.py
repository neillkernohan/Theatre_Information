from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, IntegerField, TextAreaField, SubmitField
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
    quantity = IntegerField('Quantity', validators=[DataRequired(), NumberRange(min=1)], default=1)
    storage_location = StringField('Storage Location', validators=[Optional(), Length(max=255)])
    status = SelectField('Status', choices=[
        ('available', 'Available'),
        ('in_use', 'In Use'),
        ('needs_repair', 'Needs Repair'),
        ('retired', 'Retired'),
    ], validators=[DataRequired()])
    description = TextAreaField('Description', validators=[Optional()])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Save')
