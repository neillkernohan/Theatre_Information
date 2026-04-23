from flask import render_template, redirect, url_for, flash, request
import json
import secrets
from flask_login import login_user, logout_user, login_required, current_user
from auditions import auditions_bp
from auditions.models import db, User, Registration, Show, AuditionSlot
from auditions.forms import ActorRegistrationForm, LoginForm


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

        # Collect volunteer interests
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

        # Parse acting experience from form
        experience_json = request.form.get('acting_experience_json', '[]')
        try:
            acting_experience = json.loads(experience_json)
        except (json.JSONDecodeError, TypeError):
            acting_experience = []

        user = User(
            email=form.email.data.lower().strip(),
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            phone=form.phone.data.strip() if form.phone.data else None,
            pronouns=pronouns,
            contact_email_ok=(form.contact_email_ok.data == 'yes'),
            roles_auditioning_for=form.roles_auditioning_for.data.strip() if form.roles_auditioning_for.data else None,
            accept_other_role=(form.accept_other_role.data == 'yes'),
            comfortable_performing=(form.comfortable_performing.data == 'yes'),
            equity_or_actra=(form.equity_or_actra.data == 'yes'),
            schedule_conflicts=form.schedule_conflicts.data.strip() if form.schedule_conflicts.data else None,
            training=form.training.data.strip() if form.training.data else None,
            acting_experience=acting_experience if acting_experience else None,
            volunteer_interests=volunteer_interests if volunteer_interests else None,
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
        if current_user.role == 'admin':
            return redirect(url_for('auditions.admin_dashboard'))
        return redirect(url_for('auditions.actor_dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            next_page = request.args.get('next')
            if user.role == 'admin':
                return redirect(next_page or url_for('auditions.admin_dashboard'))
            return redirect(next_page or url_for('auditions.actor_dashboard'))
        flash('Invalid email or password.', 'danger')

    return render_template('auditions/login.html', form=form)


@auditions_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('auditions.admin_dashboard'))
        return redirect(url_for('auditions.actor_dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip(), role='admin').first()
        if user and user.check_password(form.password.data):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('auditions.admin_dashboard'))
        flash('Invalid admin credentials.', 'danger')

    return render_template('auditions/admin/login.html', form=form)


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
        flash(f'Welcome, {first_name}! Your account has been created.', 'success')

    login_user(user)
    next_page = request.args.get('next')
    if user.role == 'admin':
        return redirect(next_page or url_for('auditions.admin_dashboard'))
    return redirect(next_page or url_for('auditions.actor_dashboard'))


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
