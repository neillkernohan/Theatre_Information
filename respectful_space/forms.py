from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional, ValidationError


class SignForm(FlaskForm):
    first_name = StringField('First name', validators=[DataRequired(), Length(max=100)])
    last_name = StringField('Last name', validators=[DataRequired(), Length(max=100)])
    email = EmailField('Email', validators=[DataRequired(), Email(), Length(max=255)])
    production = StringField('Show or role you’re involved in',
                             validators=[Optional(), Length(max=255)],
                             description='e.g. “Mamma Mia! — cast”, “Front of house volunteer”, “Board”')
    agree = BooleanField(
        'I have read and understand Theatre Aurora’s Respectful Space Policy and agree '
        'to each of the statements above.',
        validators=[DataRequired(message='Please confirm that you agree to the policy.')])
    signature_name = StringField('Type your full name as your signature',
                                 validators=[DataRequired(), Length(max=255)])
    # Honeypot: hidden from people, filled in by spam bots.
    website = StringField('Website', validators=[Optional()])
    submit = SubmitField('Sign the policy')

    def validate_signature_name(self, field):
        typed = ' '.join(field.data.split()).lower()
        expected = ' '.join(f'{self.first_name.data or ""} {self.last_name.data or ""}'.split()).lower()
        if expected and typed != expected:
            raise ValidationError('Your signature should match the first and last name above.')


class CheckListForm(FlaskForm):
    people = TextAreaField('Emails or names, one per line', validators=[DataRequired()])
    submit = SubmitField('Check')
