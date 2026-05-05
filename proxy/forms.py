from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField, SelectField, BooleanField, DateTimeLocalField
from wtforms.validators import DataRequired, Email, Length, Optional


class MeetingForm(FlaskForm):
    title = StringField('Meeting Title', validators=[DataRequired(), Length(max=255)])
    meeting_date = DateTimeLocalField('Meeting Date & Time', validators=[DataRequired()],
                                      format='%Y-%m-%dT%H:%M')
    proxy_deadline = DateTimeLocalField('Proxy Submission Deadline', validators=[DataRequired()],
                                        format='%Y-%m-%dT%H:%M')
    description = TextAreaField('Notice of Meeting / Description', validators=[Optional()])
    notify_email = StringField('Notification Email',
                               validators=[Optional(), Email(), Length(max=255)],
                               description='Proxy submissions are emailed here (e.g. secretary@theatreaurora.com)')
    status = SelectField('Status', choices=[
        ('draft', 'Draft'),
        ('open', 'Open — accepting proxies'),
        ('closed', 'Closed'),
    ])
    submit = SubmitField('Save Meeting')


class ProxyForm(FlaskForm):
    holder_name = SelectField('Proxy Holder', validators=[DataRequired()])
    declaration = BooleanField(
        'I hereby appoint the above member as my proxy holder to attend, act and vote on my '
        'behalf at this meeting, and hereby revoke any proxies previously given.',
        validators=[DataRequired(message='You must accept the declaration to submit a proxy.')]
    )
    signature_name = StringField('Full Name (typed as your signature)',
                                 validators=[DataRequired(), Length(max=255)])
    submit = SubmitField('Submit Proxy')
