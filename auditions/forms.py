from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, SubmitField, TelField, TextAreaField,
    SelectField, IntegerField, BooleanField, DateTimeLocalField, FieldList,
    FormField, RadioField
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError, Optional, NumberRange
from auditions.models import User
import re

_email_re = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def validate_email_list(form, field):
    """Accept a comma-separated list of email addresses."""
    if not field.data:
        return
    for addr in field.data.split(','):
        addr = addr.strip()
        if addr and not _email_re.match(addr):
            raise ValidationError(f'"{addr}" is not a valid email address.')


class ActorRegistrationForm(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired(), Length(max=100)])
    last_name = StringField('Last Name', validators=[DataRequired(), Length(max=100)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=255)])
    phone = TelField('Phone Number', validators=[DataRequired()])
    address = StringField('Street Address', validators=[Optional(), Length(max=255)])
    city = StringField('City', validators=[Optional(), Length(max=100)])
    province = StringField('Province', validators=[Optional(), Length(max=100)])
    postal_code = StringField('Postal Code', validators=[Optional(), Length(max=20)])
    pronouns = SelectField('Pronouns', choices=[
        ('he/him', 'He/Him'),
        ('she/her', 'She/Her'),
        ('they/them', 'They/Them'),
        ('he/they', 'He/They'),
        ('she/they', 'She/They'),
        ('other', 'Other / Prefer to self-describe'),
    ], validators=[DataRequired()])
    pronouns_other = StringField('Pronouns (self-describe)', validators=[Optional(), Length(max=50)])
    contact_email_ok = SelectField(
        'Email consent',
        choices=[('yes', 'Yes'), ('no', 'No')],
        default='yes'
    )

    past_member = RadioField(
        'Have you been a member of Theatre Aurora in the past?',
        choices=[('yes', 'Yes'), ('no', 'No')],
        validators=[DataRequired()]
    )
    hear_about_us = StringField(
        'How did you hear about us?',
        validators=[Optional(), Length(max=255)]
    )

    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(), EqualTo('password', message='Passwords must match.')
    ])
    submit = SubmitField('Create Account')

    def validate_email(self, field):
        if User.query.filter_by(email=field.data.lower()).first():
            raise ValidationError('An account with this email already exists.')


class ActorProfileForm(FlaskForm):
    """Profile fields shown on audition registration and the Edit Profile page."""
    comfortable_performing = SelectField(
        'Are you comfortable performing the following on stage: kissing, smoking, physical violence, swearing, using weapons?',
        choices=[('yes', 'Yes'), ('no', 'No')], default='yes'
    )
    equity_or_actra = SelectField("Are you currently a member of Actor's Equity or ACTRA?",
                                  choices=[('no', 'No'), ('yes', 'Yes')], default='no')
    training = TextAreaField('Training', validators=[Optional()])

    # Volunteer interests
    interest_choreographer = BooleanField('Choreographer')
    interest_concession = BooleanField('Concession Assistant (Smart Serve Certified)')
    interest_costume_design = BooleanField('Costume Design')
    interest_director = BooleanField('Director')
    interest_lighting_design = BooleanField('Lighting Design')
    interest_lighting_operator = BooleanField('Lighting Operator')
    interest_music_director = BooleanField('Music Director')
    interest_photography = BooleanField('Photography')
    interest_producer = BooleanField('Producer')
    interest_props_master = BooleanField('Props Master')
    interest_set_build = BooleanField('Set Build')
    interest_set_design = BooleanField('Set Design')
    interest_set_dressing = BooleanField('Set Dressing')
    interest_set_painting = BooleanField('Set Painting')
    interest_sound_design = BooleanField('Sound Design')
    interest_sound_operator = BooleanField('Sound Operator')
    interest_stagehand = BooleanField('Stagehand')
    interest_stage_manager = BooleanField('Stage Manager')
    interest_usher = BooleanField('Usher')

    submit = SubmitField('Save Profile')


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Log In')


class ForgotPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Send Reset Link')


class ResetPasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm New Password', validators=[
        DataRequired(), EqualTo('password', message='Passwords must match.')
    ])
    submit = SubmitField('Reset Password')


class CustomFieldForm(FlaskForm):
    """Sub-form for a single custom registration field."""
    class Meta:
        csrf = False

    field_name = StringField('Field Name', validators=[DataRequired(), Length(max=100)])
    field_type = SelectField('Type', choices=[
        ('text', 'Text'),
        ('textarea', 'Long Text'),
        ('select', 'Dropdown'),
        ('checkbox', 'Checkbox'),
    ])
    required = BooleanField('Required')
    options = StringField('Options (comma-separated, for dropdowns)')


class AuditionDateForm(FlaskForm):
    """Sub-form for a single audition date with start time."""
    class Meta:
        csrf = False

    date = StringField('Date', validators=[DataRequired()])
    start_time = StringField('Start Time', validators=[DataRequired()])


class ShowForm(FlaskForm):
    title = StringField('Show Title', validators=[DataRequired(), Length(max=255)])
    description = TextAreaField('Description')
    scheduling_mode = SelectField('Scheduling Mode', choices=[
        ('block', 'Time Blocks (multiple people per block)'),
        ('slot', 'Individual Slots (one person per slot)')
    ], validators=[DataRequired()])
    allow_choice = BooleanField('Allow actors to choose their time', default=True)

    # Block mode fields
    max_per_block = IntegerField('Max People per Block', validators=[Optional(), NumberRange(min=1)])
    block_duration_minutes = IntegerField('Block Duration (minutes)', default=90,
                                          validators=[Optional(), NumberRange(min=15)])
    blocks_per_night = IntegerField('Blocks per Night', default=2,
                                    validators=[Optional(), NumberRange(min=1, max=10)])

    # Slot mode fields
    slot_duration_minutes = SelectField('Slot Duration', choices=[
        ('10', '10 minutes'),
        ('15', '15 minutes'),
        ('20', '20 minutes'),
    ], validators=[Optional()])
    total_slot_hours = StringField('Total Hours per Night', default='3',
                                   validators=[Optional()])

    # Registration window
    registration_open = DateTimeLocalField('Registration Opens',
                                           format='%Y-%m-%dT%H:%M',
                                           validators=[DataRequired()])
    registration_close = DateTimeLocalField('Registration Closes',
                                            format='%Y-%m-%dT%H:%M',
                                            validators=[DataRequired()])

    # Admin notifications
    notify_email = StringField('Notify Email(s)', validators=[Optional(), Length(max=255), validate_email_list])

    submit = SubmitField('Save Show')


class GenerateSlotsForm(FlaskForm):
    """Form for adding audition dates and generating slots."""
    submit = SubmitField('Generate Slots')


