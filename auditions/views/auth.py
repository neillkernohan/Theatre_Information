from flask import render_template, redirect, url_for, flash, request
import json
import secrets
from flask_login import login_user, logout_user, login_required, current_user
from auditions import auditions_bp
from auditions.models import db, User, Registration, Show, AuditionSlot
from auditions.forms import ActorRegistrationForm, ActorProfileForm, LoginForm, ForgotPasswordForm, ResetPasswordForm


@auditions_bp.route('/register', methods=['GET', 'POST'])
def actor_register():
    if current_user.is_authenticated:
        return redirect(url_for('auditions.actor_dashboard'))

    form = ActorRegistrationForm()
    if form.validate_on_submit():
        pronouns = form.pronouns.data
        if pronouns == 'other' and form.pronouns_other.data:
            pronouns = form.pronouns_other.data.strip()
        elif pronouns == '':
            pronouns = None

        is_past_member = (form.past_member.data == 'yes')
        hear_about_us = None if is_past_member else (form.hear_about_us.data.strip() or None)

        user = User(
            email=form.email.data.lower().strip(),
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            phone=form.phone.data.strip() if form.phone.data else None,
            address=form.address.data.strip() if form.address.data else None,
            city=form.city.data.strip() if form.city.data else None,
            province=form.province.data.strip() if form.province.data else None,
            postal_code=form.postal_code.data.strip() if form.postal_code.data else None,
            pronouns=pronouns,
            contact_email_ok=(form.contact_email_ok.data == 'yes'),
            past_member=is_past_member,
            hear_about_us=hear_about_us,
            role='actor'
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash('Account created successfully! Welcome to Theatre Aurora Auditions.', 'success')
        return redirect(url_for('auditions.actor_dashboard'))

    return render_template('auditions/register.html', form=form)


@auditions_bp.route('/login', methods=['GET', 'POST'])
def actor_login():
    if current_user.is_authenticated:
        if current_user.role in ('admin', 'viewer'):
            return redirect(url_for('auditions.admin_dashboard'))
        return redirect(url_for('auditions.actor_dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            next_page = request.args.get('next')
            if user.role in ('admin', 'viewer'):
                return redirect(next_page or url_for('auditions.admin_dashboard'))
            return redirect(next_page or url_for('auditions.actor_dashboard'))
        flash('Invalid email or password.', 'danger')

    return render_template('auditions/login.html', form=form)


@auditions_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated:
        if current_user.role in ('admin', 'viewer'):
            return redirect(url_for('auditions.admin_dashboard'))
        return redirect(url_for('auditions.actor_dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and user.check_password(form.password.data) and user.role in ('admin', 'viewer'):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('auditions.admin_dashboard'))
        flash('Invalid admin credentials.', 'danger')

    return render_template('auditions/admin/login.html', form=form)


@auditions_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer
    from auditions.email import send_password_reset_email

    if current_user.is_authenticated:
        return redirect(url_for('auditions.actor_dashboard'))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        # Always show the same message to avoid email enumeration
        if user and user.role == 'actor':
            s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
            token = s.dumps(user.email, salt='password-reset')
            reset_url = url_for('auditions.reset_password', token=token, _external=True)
            send_password_reset_email(user, reset_url)
        flash('If that email is registered, a reset link has been sent.', 'info')
        return redirect(url_for('auditions.actor_login'))

    return render_template('auditions/forgot_password.html', form=form)


@auditions_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

    if current_user.is_authenticated:
        return redirect(url_for('auditions.actor_dashboard'))

    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = s.loads(token, salt='password-reset', max_age=3600)  # 1 hour
    except SignatureExpired:
        flash('That reset link has expired. Please request a new one.', 'warning')
        return redirect(url_for('auditions.forgot_password'))
    except BadSignature:
        flash('That reset link is invalid.', 'danger')
        return redirect(url_for('auditions.forgot_password'))

    user = User.query.filter_by(email=email, role='actor').first()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auditions.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash('Your password has been reset. Please log in.', 'success')
        return redirect(url_for('auditions.actor_login'))

    return render_template('auditions/reset_password.html', form=form)


@auditions_bp.route('/google/login')
def google_login():
    # Lazy import to avoid circular dependency — oauth is in app.py
    from app import oauth
    redirect_uri = url_for('auditions.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auditions_bp.route('/google/callback')
def google_callback():
    from app import oauth
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        flash('Google login failed. Please try again.', 'danger')
        return redirect(url_for('auditions.actor_login'))

    userinfo = token.get('userinfo') or {}
    email = userinfo.get('email', '').lower().strip()
    first_name = userinfo.get('given_name', '') or ''
    last_name = userinfo.get('family_name', '') or ''

    if not email:
        flash('Could not retrieve your email from Google. Please try again.', 'danger')
        return redirect(url_for('auditions.actor_login'))

    if not userinfo.get('email_verified'):
        flash('Your Google account email is not verified.', 'danger')
        return redirect(url_for('auditions.actor_login'))

    user = User.query.filter_by(email=email).first()

    is_new = False
    if not user:
        # Create a new actor account from the Google profile
        user = User(
            email=email,
            first_name=first_name or 'Unknown',
            last_name=last_name,
            role='actor',
            contact_email_ok=True
        )
        user.set_password(secrets.token_hex(32))  # random — Google auth only
        db.session.add(user)
        db.session.commit()
        is_new = True

    login_user(user)

    # New Google accounts need to complete their profile
    if is_new:
        flash(f'Welcome, {first_name}! Please complete your profile to continue.', 'info')
        return redirect(url_for('auditions.complete_profile'))

    next_page = request.args.get('next')
    if user.role in ('admin', 'viewer'):
        return redirect(next_page or url_for('auditions.admin_dashboard'))
    return redirect(next_page or url_for('auditions.actor_dashboard'))


@auditions_bp.route('/complete-profile', methods=['GET', 'POST'])
@login_required
def complete_profile():
    """Collect missing fields for accounts created via Google OAuth."""
    if request.method == 'POST':
        current_user.phone = request.form.get('phone', '').strip() or None
        current_user.address = request.form.get('address', '').strip() or None
        current_user.city = request.form.get('city', '').strip() or None
        current_user.province = request.form.get('province', '').strip() or None
        current_user.postal_code = request.form.get('postal_code', '').strip() or None
        pronouns_val = request.form.get('pronouns', '').strip()
        if pronouns_val == 'other':
            pronouns_val = request.form.get('pronouns_other', '').strip() or 'other'
        current_user.pronouns = pronouns_val or None
        current_user.contact_email_ok = (request.form.get('contact_email_ok') == 'yes')
        past_raw = request.form.get('past_member')
        current_user.past_member = True if past_raw == 'yes' else (False if past_raw == 'no' else None)
        current_user.hear_about_us = request.form.get('hear_about_us', '').strip() or None
        db.session.commit()
        flash('Welcome! Your profile is all set.', 'success')
        return redirect(url_for('auditions.actor_dashboard'))

    return render_template('auditions/complete_profile.html')


@auditions_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auditions.actor_login'))


@auditions_bp.route('/my-auditions')
@login_required
def actor_dashboard():
    registrations = Registration.query.filter_by(
        user_id=current_user.id
    ).filter(Registration.status != 'cancelled').order_by(
        Registration.created_at.desc()
    ).all()
    return render_template('auditions/public/my_auditions.html', registrations=registrations)


@auditions_bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = ActorProfileForm()

    if form.validate_on_submit():
        # Save contact fields (plain request.form — not in ActorProfileForm)
        current_user.phone = request.form.get('phone', '').strip() or None
        current_user.address = request.form.get('address', '').strip() or None
        current_user.city = request.form.get('city', '').strip() or None
        current_user.province = request.form.get('province', '').strip() or None
        current_user.postal_code = request.form.get('postal_code', '').strip() or None
        current_user.pronouns = request.form.get('pronouns', '').strip() or None
        _save_profile_from_form(form, current_user)
        db.session.commit()
        flash('Your profile has been updated.', 'success')
        return redirect(url_for('auditions.actor_dashboard'))

    # Pre-populate form on GET
    if request.method == 'GET':
        _prepopulate_profile_form(form, current_user)

    return render_template('auditions/public/edit_profile.html', form=form,
                           acting_experience_json=json.dumps(current_user.acting_experience or []))


def _save_profile_from_form(form, user):
    """Save ActorProfileForm data back to the user record."""
    interest_fields = [
        ('interest_choreographer', 'Choreographer'),
        ('interest_concession', 'Concession Assistant (Smart Serve Certified)'),
        ('interest_costume_design', 'Costume Design'),
        ('interest_director', 'Director'),
        ('interest_lighting_design', 'Lighting Design'),
        ('interest_lighting_operator', 'Lighting Operator'),
        ('interest_music_director', 'Music Director'),
        ('interest_photography', 'Photography'),
        ('interest_producer', 'Producer'),
        ('interest_props_master', 'Props Master'),
        ('interest_set_build', 'Set Build'),
        ('interest_set_design', 'Set Design'),
        ('interest_set_dressing', 'Set Dressing'),
        ('interest_set_painting', 'Set Painting'),
        ('interest_sound_design', 'Sound Design'),
        ('interest_sound_operator', 'Sound Operator'),
        ('interest_stagehand', 'Stagehand'),
        ('interest_stage_manager', 'Stage Manager'),
        ('interest_usher', 'Usher'),
    ]
    volunteer_interests = [
        label for field_name, label in interest_fields
        if getattr(form, field_name).data
    ]

    experience_json = request.form.get('acting_experience_json', '[]')
    try:
        acting_experience = json.loads(experience_json)
    except (json.JSONDecodeError, TypeError):
        acting_experience = []

    def _s(val):
        return val.strip() if val else None

    user.comfortable_performing = (form.comfortable_performing.data == 'yes')
    user.equity_or_actra = (form.equity_or_actra.data == 'yes')
    user.training = _s(form.training.data)
    user.acting_experience = acting_experience if acting_experience else None
    user.volunteer_interests = volunteer_interests if volunteer_interests else None


def _prepopulate_profile_form(form, user):
    """Pre-populate an ActorProfileForm from a user's saved profile."""
    vi = user.volunteer_interests or []
    label_to_field = {
        'Choreographer': 'interest_choreographer',
        'Concession Assistant (Smart Serve Certified)': 'interest_concession',
        'Costume Design': 'interest_costume_design',
        'Director': 'interest_director',
        'Lighting Design': 'interest_lighting_design',
        'Lighting Operator': 'interest_lighting_operator',
        'Music Director': 'interest_music_director',
        'Photography': 'interest_photography',
        'Producer': 'interest_producer',
        'Props Master': 'interest_props_master',
        'Set Build': 'interest_set_build',
        'Set Design': 'interest_set_design',
        'Set Dressing': 'interest_set_dressing',
        'Set Painting': 'interest_set_painting',
        'Sound Design': 'interest_sound_design',
        'Sound Operator': 'interest_sound_operator',
        'Stagehand': 'interest_stagehand',
        'Stage Manager': 'interest_stage_manager',
        'Usher': 'interest_usher',
    }
    form.comfortable_performing.data = 'yes' if user.comfortable_performing else 'no'
    form.equity_or_actra.data = 'yes' if user.equity_or_actra else 'no'
    form.training.data = user.training or ''
    for label, field_name in label_to_field.items():
        getattr(form, field_name).data = label in vi
