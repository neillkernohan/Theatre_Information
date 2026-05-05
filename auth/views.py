from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.routing import BuildError
from auth import auth_bp
from auth.models import db, User, THEATREAURORA_DOMAIN
from auth.forms import LoginForm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_redirect(user):
    """Landing page after a successful login, based on role.

    Staff (admin/viewer/@theatreaurora.com) land on the core dashboard home
    page; actors land on their auditions dashboard.  Falls back gracefully
    when the core dashboard routes aren't registered (e.g. in tests).
    """
    if user.role in ('admin', 'viewer') or user.is_staff:
        try:
            return url_for('home')
        except BuildError:
            return url_for('auditions.admin_dashboard')
    return url_for('auditions.actor_dashboard')


def _record_login(user):
    user.touch_last_login()
    db.session.commit()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(_default_redirect(current_user))

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.lower().strip()

        # Staff must use Google — block password attempts for @theatreaurora.com
        if email.endswith(THEATREAURORA_DOMAIN):
            flash('Theatre Aurora staff accounts must sign in with Google.', 'warning')
            return redirect(url_for('auth.login'))

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            _record_login(user)
            next_page = request.args.get('next')
            return redirect(next_page or _default_redirect(user))
        flash('Invalid email or password.', 'danger')

    return render_template('auth/login.html', form=form)


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

@auth_bp.route('/google')
def google_login():
    from app import oauth
    redirect_uri = url_for('auth.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route('/google/callback')
def google_callback():
    from app import oauth
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        flash('Google login failed. Please try again.', 'danger')
        return redirect(url_for('auth.login'))

    userinfo = token.get('userinfo') or {}
    email = userinfo.get('email', '').lower().strip()
    first_name = userinfo.get('given_name', '') or ''
    last_name = userinfo.get('family_name', '') or ''
    google_id = userinfo.get('sub', '')

    if not email:
        flash('Could not retrieve your email from Google. Please try again.', 'danger')
        return redirect(url_for('auth.login'))

    if not userinfo.get('email_verified'):
        flash('Your Google account email is not verified.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first()

    is_new = False
    if not user:
        # New user — role determined by domain
        role = 'viewer' if email.endswith(THEATREAURORA_DOMAIN) else 'actor'
        user = User(
            email=email,
            first_name=first_name or 'Unknown',
            last_name=last_name,
            role=role,
            google_id=google_id,
            contact_email_ok=True,
        )
        db.session.add(user)
        db.session.commit()
        is_new = True
    else:
        # Update google_id on first Google login for existing accounts
        if google_id and not user.google_id:
            user.google_id = google_id
            db.session.commit()

    login_user(user)
    _record_login(user)

    next_page = request.args.get('next')

    # New actor accounts need to complete their profile
    if is_new and user.role == 'actor':
        flash(f'Welcome, {first_name}! Please complete your profile to continue.', 'info')
        return redirect(url_for('auditions.complete_profile'))

    return redirect(next_page or _default_redirect(user))


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))
