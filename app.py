from flask import Flask, request, jsonify, session, redirect, url_for, render_template
import mysql.connector
from datetime import datetime, timedelta, timezone, time as dt_time, date
from dateutil import tz
import re
from zoneinfo import ZoneInfo
import os
import os.path
import csv
import time
from decimal import Decimal
import json
from dotenv import load_dotenv
from functools import wraps
from authlib.integrations.flask_client import OAuth
import click
import hmac
import hashlib
import smtplib
import sys
from email.mime.text import MIMEText

import random

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
APP_PASSWORD = os.getenv("APP_PASSWORD")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
CANADA_POST_API_KEY = os.getenv("CANADA_POST_API_KEY", '')
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL")

used_colors = set()

def select_season():
    # Today's date
    today = date.today()
    
    # Define the start of each season
    seasons = [
        {"start": date(2025, 7, 1), "label": "2025-07-01"},
        {"start": date(2024, 7, 1), "label": "2024-07-01"},
        {"start": date(2023, 7, 1), "label": "2023-07-01"}
    ]
    
    # Check which season today's date falls into
    for season in seasons:
        season_end = date(season["start"].year + 1, 6, 30)  # June 30th of the next year
        if season["start"] <= today <= season_end:
            return season["label"]
    
    return "Current date does not fall within the defined seasons."

def dynamic_colors():
    while True:  # Keep trying until we find a new color
        r = random.randint(0, 255)
        g = random.randint(0, 255)
        b = random.randint(0, 255)
        color = f"rgb({r},{g},{b})"
        
        if color not in used_colors:
            used_colors.add(color)
            return color

default_timezone = ZoneInfo("America/New_York")

# Regex pattern for ISO 8601 datetime format with timezone
datetime_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-\d{2}:\d{2}$"
# Regex pattern for ISO 8601 date format
date_pattern = r"^\d{4}-\d{2}-\d{2}$"


def parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        # Handles datetime with timezone
        return datetime.strptime(date_str[:10], "%Y-%m-%d")

def combine_events(events):
    combined_events = []
    i = 0
    while i < len(events):
        current_event = events[i]
        if current_event['title'] == 'Booked All Day':
            # Try to combine with following events
            j = i + 1
            while j < len(events):
                next_event = events[j]
                if next_event['title'] == 'Booked All Day' and current_event['end']  == next_event['start']:
                    # Extend the current event's end date to the next event's end date
                    current_event['end'] = next_event['end']
                    j += 1
                else:
                    break
            i = j
        else:
            i += 1
        combined_events.append(current_event)
    return combined_events

def check_string_format(s):
    if re.match(datetime_pattern, s):
        return "datetime with timezone"
    elif re.match(date_pattern, s):
        return "date only"
    else:
        return "unknown format"
    
def parse_date_with_timezone(date_str):
    """Parse a date string and return a timezone-aware datetime object."""
    # Assuming date_str is in ISO 8601 format; adjust parsing as needed
    return datetime.fromisoformat(date_str).replace(tzinfo=default_timezone)

def parse_date_utc(date_time):
    return date_time.replace(tzinfo=timezone.utc).isoformat()
    
def categorize_event_time(start_str, end_str):
    # Parse the ISO 8601 formatted strings into datetime objects
    start_dt = datetime.fromisoformat(start_str)
    end_dt = datetime.fromisoformat(end_str)

    # Define the category time ranges
    morning_start, morning_end = start_dt.replace(hour=9, minute=0), start_dt.replace(hour=12, minute=0)
    afternoon_start, afternoon_end = start_dt.replace(hour=13, minute=0), start_dt.replace(hour=17, minute=0)
    evening_start, evening_end = start_dt.replace(hour=18, minute=0), start_dt.replace(hour=22, minute=0)

    categories = set()

    # Check if the event spans morning, afternoon, or evening
    if start_dt < morning_end and end_dt > morning_start:
        categories.add("morning")
    if start_dt < afternoon_end and end_dt > afternoon_start:
        categories.add("afternoon")
    if start_dt < evening_end and end_dt > evening_start:
        categories.add("evening")

    # Determine if the event spans multiple categories
    if len(categories) > 1:
        return "spans " + ", ".join(categories)
    elif len(categories) == 1:
        return categories.pop()
    else:
        return "does not fall into the defined categories"
    
def get_fiscal_year_start(input_date):
    # Check if the month is before July (the start of the fiscal year)
    if input_date.month < 7:
        # If before July, the fiscal year would have started on July 1 of the previous year
        return date(input_date.year - 1, 7, 1)
    else:
        # Otherwise, it starts on July 1 of the current year
        return date(input_date.year, 7, 1)


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", 'cW3(sP1;tJ4#mX2<sL6!uB1&zR0~gX4%')  # Needed for session management

# Keep users logged in for 30 days
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Google OAuth setup
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

# --- Auditions Module Setup (optional) ---
# The auditions module is optional — the core site runs without it.
# If the 'auditions' package or its dependencies are missing (e.g. on a
# server that hasn't been set up for auditions yet), skip this whole block
# instead of crashing the entire app.
AUDITIONS_ENABLED = False
try:
    from flask_login import LoginManager
    from flask_mail import Mail
    from flask_wtf.csrf import CSRFProtect, CSRFError
    from auditions.models import db, User
    from auditions import auditions_bp
    from proxy import proxy_bp
    from proxy.models import ProxyMember, ProxyMeeting, ProxySubmission  # noqa: F401 — ensure tables are registered

    # SQLAlchemy config for auditions database
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('AUDITIONS_DB_URI')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # File upload config
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'auditions', 'uploads')
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

    # Flask-Mail config (Gmail SMTP)
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'Theatre Aurora Auditions <auditions@theatreaurora.com>')

    # Initialize extensions
    db.init_app(app)

    login_manager = LoginManager(app)
    login_manager.login_view = 'auditions.actor_login'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    mail = Mail(app)
    csrf = CSRFProtect(app)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        from flask import jsonify
        return jsonify({'error': 'CSRF validation failed', 'detail': e.description}), 400

    # Register blueprints
    app.register_blueprint(auditions_bp)
    app.register_blueprint(proxy_bp)

    # CLI commands for auditions
    @app.cli.command('init-auditions-db')
    def init_auditions_db():
        """Create all auditions database tables."""
        with app.app_context():
            db.create_all()
        click.echo('Auditions database tables created.')

    @app.cli.command('create-admin')
    @click.option('--email', prompt='Admin email')
    @click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
    @click.option('--first-name', prompt='First name')
    @click.option('--last-name', prompt='Last name')
    def create_admin(email, password, first_name, last_name):
        """Create an admin user for the auditions module."""
        with app.app_context():
            if User.query.filter_by(email=email.lower()).first():
                click.echo(f'Error: User with email {email} already exists.')
                return
            user = User(
                email=email.lower().strip(),
                first_name=first_name.strip(),
                last_name=last_name.strip(),
                role='admin'
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            click.echo(f'Admin user {first_name} {last_name} ({email}) created successfully.')

    @app.cli.command('create-viewer')
    @click.option('--email', prompt='Viewer email')
    @click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
    @click.option('--first-name', prompt='First name')
    @click.option('--last-name', prompt='Last name')
    def create_viewer(email, password, first_name, last_name):
        """Create a viewer (read-only admin) user for the auditions module."""
        with app.app_context():
            if User.query.filter_by(email=email.lower()).first():
                click.echo(f'Error: User with email {email} already exists.')
                return
            user = User(
                email=email.lower().strip(),
                first_name=first_name.strip(),
                last_name=last_name.strip(),
                role='viewer'
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            click.echo(f'Viewer user {first_name} {last_name} ({email}) created successfully.')

    @app.cli.command('reset-password')
    @click.option('--email', prompt='User email')
    @click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
    def reset_password(email, password):
        """Reset the password for any auditions user."""
        with app.app_context():
            user = User.query.filter_by(email=email.lower().strip()).first()
            if not user:
                click.echo(f'Error: No user found with email {email}.')
                return
            user.set_password(password)
            db.session.commit()
            click.echo(f'Password reset for {user.first_name} {user.last_name} ({user.email}).')

    @app.cli.command('send-reminders')
    @click.option('--dry-run', is_flag=True, default=False,
                  help='Print who would be emailed without actually sending.')
    def send_reminders(dry_run):
        """Send audition reminder emails to actors whose slot is tomorrow."""
        from datetime import date, timedelta
        from auditions.models import AuditionSlot, Registration, EmailLog
        from auditions.email import send_reminder_email

        with app.app_context():
            tomorrow = date.today() + timedelta(days=1)
            click.echo(f'Looking for auditions on {tomorrow.strftime("%A, %B %d, %Y")}...')

            slots = AuditionSlot.query.filter_by(date=tomorrow).all()
            if not slots:
                click.echo('No audition slots tomorrow. Nothing to send.')
                return

            sent = 0
            skipped = 0
            failed = 0

            for slot in slots:
                confirmed = Registration.query.filter_by(
                    slot_id=slot.id, status='confirmed'
                ).all()

                for reg in confirmed:
                    # Check if reminder already sent for this registration
                    already_sent = EmailLog.query.filter_by(
                        registration_id=reg.id,
                        email_type='reminder',
                        status='sent'
                    ).first()

                    if already_sent:
                        click.echo(f'  SKIP  {reg.user.email} — reminder already sent')
                        skipped += 1
                        continue

                    if dry_run:
                        click.echo(
                            f'  DRY   {reg.user.first_name} {reg.user.last_name} '
                            f'<{reg.user.email}> — '
                            f'{slot.start_time.strftime("%I:%M %p")}'
                        )
                        sent += 1
                    else:
                        success = send_reminder_email(reg)
                        if success:
                            click.echo(
                                f'  SENT  {reg.user.first_name} {reg.user.last_name} '
                                f'<{reg.user.email}> — '
                                f'{slot.start_time.strftime("%I:%M %p")}'
                            )
                            sent += 1
                        else:
                            click.echo(
                                f'  FAIL  {reg.user.email}',
                                err=True
                            )
                            failed += 1

            label = 'Would send' if dry_run else 'Sent'
            click.echo(f'\nDone. {label}: {sent}  Skipped: {skipped}  Failed: {failed}')

    AUDITIONS_ENABLED = True
except (ImportError, ModuleNotFoundError) as _auditions_err:
    import sys as _sys
    print(f"[Theatre_Info] Auditions module disabled: {_auditions_err}", file=_sys.stderr)
# --- End Auditions Module Setup ---

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            session['next_url'] = request.path
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def is_authorized(email):
    """Check if an email is in the Authorized_Users table."""
    db = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE
    )
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM Authorized_Users WHERE email = %s", (email.lower(),))
    count = cursor.fetchone()[0]
    db.close()
    return count > 0

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/auth/google')
def auth_google():
    redirect_uri = url_for('auth_google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def auth_google_callback():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')
    if not user_info:
        user_info = google.userinfo()

    email = user_info.get('email', '').lower()
    name = user_info.get('name', '')

    if not is_authorized(email):
        return render_template('login.html',
            error=f"'{email}' is not authorized to access this site. Contact your administrator.")

    session.permanent = True
    session['logged_in'] = True
    session['user_email'] = email
    session['user_name'] = name
    next_url = session.pop('next_url', None)
    return redirect(next_url or url_for('home'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/SeasonTotals')
@login_required
def SeasonTotals():
    db = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE
    )
    cursor = db.cursor()

    this_season = request.args.get('this_season', type=str)
    if this_season is None:
        this_season = select_season()

    shows_only = 1 if request.args.get('showsOnly', 'false') == 'true' else 0

    update_cursor = db.cursor()
    update_cursor.execute(
        "SELECT Update_date_time FROM Theatre_Information.Updates ORDER BY Update_date_time DESC LIMIT 1"
    )
    update_row = update_cursor.fetchone()
    formatted_update = update_row[0].strftime('%B %-d, %Y at %-I:%M %p') if update_row else 'Not available'

    seasons_cursor = db.cursor()
    seasons_cursor.execute(
        "SELECT DATE_FORMAT(Season, '%Y-%m-%d') AS s FROM Theatre_Information.Ticket_Info GROUP BY Season ORDER BY Season DESC"
    )
    seasons = [row[0] for row in seasons_cursor.fetchall()]

    cursor.callproc('GetSeasonShowTotals', (this_season, shows_only))
    for result in cursor.stored_results():
        show_rows = result.fetchall()

    # Previous season for comparison
    prev_season = seasons[seasons.index(this_season) + 1] if this_season in seasons and seasons.index(this_season) + 1 < len(seasons) else None
    prev_show_rows = []
    if prev_season:
        prev_cursor = db.cursor()
        prev_cursor.callproc('GetSeasonShowTotals', (prev_season, shows_only))
        for result in prev_cursor.stored_results():
            prev_show_rows = result.fetchall()

    # Subscription comparison for this season and previous season
    sub_seasons = [this_season] + ([prev_season] if prev_season else [])
    sub_query = """
        SELECT TI.Season, TI.Person_type_edited,
               ROUND(SUM(TI.Item_count) / pkg.max_shows) AS subscriber_count,
               SUM(TI.Amount) AS sales
        FROM Theatre_Information.Ticket_Info TI
        JOIN (
            SELECT s.Season, MAX(sc.show_count) AS max_shows
            FROM (SELECT DISTINCT Season FROM Theatre_Information.Ticket_Info WHERE Subscription_package IS NOT NULL AND Subscription_package != '') s
            JOIN (
                SELECT Season, Subscription_package, COUNT(DISTINCT Show_name) AS show_count
                FROM Theatre_Information.Ticket_Info
                WHERE Subscription_package IS NOT NULL AND Subscription_package != ''
                GROUP BY Season, Subscription_package
            ) sc ON s.Season = sc.Season
            GROUP BY s.Season
        ) pkg ON TI.Season = pkg.Season
        WHERE TI.Season IN ({})
          AND TI.Subscription_package IS NOT NULL AND TI.Subscription_package != ''
          AND TI.Transaction_type != 'Reserve'
        GROUP BY TI.Season, TI.Person_type_edited
        ORDER BY TI.Season DESC,
            CASE TI.Person_type_edited WHEN 'Regular' THEN 1 WHEN 'Senior' THEN 2 WHEN 'Student' THEN 3 ELSE 4 END
    """.format(','.join(['%s'] * len(sub_seasons)))
    sub_cursor = db.cursor()
    sub_cursor.execute(sub_query, sub_seasons)
    sub_raw = sub_cursor.fetchall()

    # Organise subscription data into dicts keyed by (season, person_type)
    sub_data = {}
    for row in sub_raw:
        sub_data[(row[0], row[1])] = {'count': int(row[2] or 0), 'sales': float(row[3] or 0)}

    db.close()

    person_types = ['Regular', 'Senior', 'Student']

    def sub_row(season, pt):
        return sub_data.get((season, pt), {'count': 0, 'sales': 0.0})

    # Build subscription comparison list: [type, this_count, this_sales, prev_count, prev_sales]
    sub_rows = []
    for pt in person_types:
        cur_d = sub_row(this_season, pt)
        prev_d = sub_row(prev_season, pt) if prev_season else {'count': 0, 'sales': 0.0}
        sub_rows.append((pt, cur_d['count'], cur_d['sales'], prev_d['count'], prev_d['sales']))

    # Ticket type totals from show_rows for comparison
    def sum_col(rows, idx):
        return sum(r[idx] for r in rows)

    ticket_types = [
        ('Regular', 2),
        ('Senior', 3),
        ('Youth', 4),
    ]
    ticket_rows = []
    for label, idx in ticket_types:
        cur_v = sum_col(show_rows, idx)
        prev_v = sum_col(prev_show_rows, idx) if prev_show_rows else 0
        ticket_rows.append((label, cur_v, prev_v))
    ticket_totals = (sum_col(show_rows, 5), sum_col(prev_show_rows, 5) if prev_show_rows else 0)

    return render_template('SeasonTotals.html',
        formatted_update=formatted_update,
        this_season=this_season,
        prev_season=prev_season,
        seasons=seasons,
        show_rows=show_rows,
        shows_only=shows_only,
        ticket_rows=ticket_rows,
        ticket_totals=ticket_totals,
        sub_rows=sub_rows)

# @app.route('/TotalSales')
# def TotalSales():
#     Ticket_Data_DB = mysql.connector.connect(
#         host=MYSQL_HOST,
#         user=MYSQL_USER,
#         password=MYSQL_PASSWORD,
#         database=MYSQL_DATABASE
#     )

#     data = Ticket_Data_DB.cursor()

#     data.callproc('GetTicketTotals', ('2023-07-01',0))
#     for result in data.stored_results():
#         ticket_data = result.fetchall()

#     data.callproc('GetSeasonTotals', ('2023-07-01',0))
#     for result in data.stored_results():
#         season_data = result.fetchall()

#     data.callproc('GetSeasonTotals', ('2022-07-01',0))
#     for result in data.stored_results():
#         last_season_data = result.fetchall()
    
#     data.callproc('GetCommentsSeasonCount', ('2023-07-01',))
#     for result in data.stored_results():
#         comments_season_count = result.fetchall()

#     data.callproc('GetDayAverages')
#     for result in data.stored_results():
#         dayaverages = result.fetchall()

#     Subscription_Cursor = Ticket_Data_DB.cursor()
#     Subscription_Cursor.callproc('GetSubscriptions', ('2023-07-01',))
#     for result in Subscription_Cursor.stored_results():
#         subscription_data = result.fetchall()

#     Updates_Cursor = Ticket_Data_DB.cursor()
#     Updates_Cursor.execute("SELECT Update_date_time FROM Theatre_Information.Updates order by Update_date_time desc limit 1;")
#     update_data=Updates_Cursor.fetchall()
#     last_update = update_data[0][0] if update_data else 'Not available'
#     # Your code to fetch last_update from the database...

#     # Parse and format the datetime
    
#     # last_update is assumed to be a datetime.datetime object
#     formatted_update = last_update.strftime('%B %-d, %Y at %-I:%M %p')

#     # Then render the template with formatted_update

#     return render_template('TotalSales.html', data=ticket_data, season_data=season_data, last_season_data=last_season_data, subscription_data = subscription_data, formatted_update=formatted_update, comments_season_count=comments_season_count, dayaverages=dayaverages)

@app.route('/ShowDetail')
@login_required
def GetShowDetail():
    show_name = request.args.get('show_name', default='', type=str)

    db = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE
    )
    cursor = db.cursor()
    cursor.callproc('GetShowDetailData', [show_name])

    results = {}
    for i, result in enumerate(cursor.stored_results()):
        results[i] = result.fetchall()

    per_perf     = results.get(0, [])   # label, Regular, Senior, Youth, Total_Sold, Reserved
    totals       = results.get(1, [[0,0,0,0,0,0,0]])[0]  # Regular,Senior,Youth,Total_Sold,Reserved,Total_Booked,Perf_Count
    per_rev      = results.get(2, [])   # label, Revenue
    financials   = results.get(3, [[0,0,0,0,0]])[0]      # Revenue,Fees,Prod_costs,Rights,Net_income
    show_info    = results.get(4, [['Unknown','',None,None]])[0]  # Show_type,Season,Opening,Closing
    ranked_tkts  = results.get(5, [])   # Show_name, Total_Tickets, Rank_Num
    ranked_rev   = results.get(6, [])   # Show_name, Revenue, Rank_Num
    prev_data    = results.get(7, [[None,0,0,0]])[0]     # Prev_Show,Days_Diff,Prev_Tickets,Prev_Revenue
    all_tkts     = results.get(8, [])   # Show_name, Show_type, Total_Tickets, Rank_Num
    all_rev      = results.get(9, [])   # Show_name, Show_type, Revenue, Rank_Num

    cursor.execute("SELECT Update_date_time FROM Theatre_Information.Updates ORDER BY Update_date_time DESC LIMIT 1")
    update_row = cursor.fetchone()
    formatted_update = update_row[0].strftime('%B %-d, %Y at %-I:%M %p') if update_row else 'Not available'
    db.close()

    show_type    = show_info[0]
    opening_date = show_info[2]
    closing_date = show_info[3]
    total_sold   = int(totals[3]) if totals[3] else 0
    revenue      = float(financials[0]) if financials[0] else 0.0

    # Compute messages
    now = datetime.now()
    is_before  = opening_date and now < opening_date
    is_running = opening_date and closing_date and opening_date <= now <= closing_date
    is_closed  = closing_date and now > closing_date

    avg_tickets = sum(float(r[1]) for r in ranked_tkts) / len(ranked_tkts) if ranked_tkts else 0
    avg_revenue = sum(float(r[1]) for r in ranked_rev)  / len(ranked_rev)  if ranked_rev  else 0
    top_ticket_show = ranked_tkts[0] if ranked_tkts else None
    top_revenue_show = ranked_rev[0] if ranked_rev else None

    if avg_tickets and avg_revenue:
        if is_before:
            phase = f"by this time before opening"
            verb  = "have sold"
        elif is_running:
            phase = f"at this point in their run"
            verb  = "have sold"
        else:
            phase = "in total"
            verb  = "sold"
        message1 = (
            f"Other shows of the type '{show_type}' {verb} an average of "
            f"{round(avg_tickets)} tickets and made ${avg_revenue:,.2f} {phase}. "
            f"'{show_name}' is at {round(total_sold/avg_tickets,1)}× average tickets sold "
            f"and {round(revenue/avg_revenue,1)}× average revenue."
        )
    else:
        message1 = ''

    if top_ticket_show and top_revenue_show:
        if show_name == top_ticket_show[0]:
            message2 = f"'{show_name}' is the top-rated show for this category."
        else:
            pct_tkts = round(total_sold / float(top_ticket_show[1]) * 100, 1)
            pct_rev  = round(revenue / float(top_revenue_show[1]) * 100, 1)
            message2 = (
                f"'{show_name}' is at {pct_tkts}% of the ticket sales and {pct_rev}% of "
                f"the revenue of the top-rated show in this category, '{top_ticket_show[0]}'."
            )
    else:
        message2 = ''

    prev_show, days_diff, prev_tickets, prev_revenue = prev_data
    if prev_show and prev_tickets and prev_revenue and float(prev_tickets) > 0 and float(prev_revenue) > 0:
        abs_days = abs(int(days_diff))
        if is_before:
            time_phrase = f"{abs_days} days before opening"
            comp_phrase = f"'{show_name}' is at {round(total_sold/float(prev_tickets),1)}× tickets sold and {round(revenue/float(prev_revenue),1)}× revenue right now."
        elif is_running:
            time_phrase = f"{abs_days} days into their run"
            comp_phrase = f"'{show_name}' is at {round(total_sold/float(prev_tickets),1)}× tickets sold and {round(revenue/float(prev_revenue),1)}× revenue right now."
        else:
            time_phrase = "by the same point in their run"
            comp_phrase = f"'{show_name}' ended at {round(total_sold/float(prev_tickets),1)}× tickets sold and {round(revenue/float(prev_revenue),1)}× revenue."
        message3 = (
            f"The last show of type '{show_type}', '{prev_show}', had sold "
            f"{int(prev_tickets):,} tickets and made ${float(prev_revenue):,.2f} {time_phrase}. "
            f"{comp_phrase}"
        )
    else:
        message3 = ''

    return render_template('ShowDetail.html',
        show_name=show_name,
        per_perf=per_perf,
        totals=totals,
        per_rev=per_rev,
        financials=financials,
        show_info=show_info,
        ranked_tkts=ranked_tkts,
        ranked_rev=ranked_rev,
        all_tkts=all_tkts,
        all_rev=all_rev,
        formatted_update=formatted_update,
        message1=message1,
        message2=message2,
        message3=message3,
    )

# @app.route('/Check_Calendar')
# def Check_Calendar():

#     # Specify the path to your CSV file
#     csv_file_path = 'events.csv'  # Make sure to adjust this to your CSV file's actual path

#     # Initialize an empty list to store the data
#     events = []

#     # Open and read the CSV file
#     with open(csv_file_path, mode='r', newline='') as file:
#         reader = csv.DictReader(file)
        
#         # Iterate over each row in the CSV and add it to the list
#         for row in reader:
#             # If 'allDay' exists in the row, convert its string representation back to a boolean
#             if 'allDay' in row:
#                 row['allDay'] = row['allDay'].lower() == 'true'
#             events.append(row)

#     return render_template('Check_Calendar.html', events=events)


# ---------------------------------------------------------------------------
# Unsubscribe helpers
# ---------------------------------------------------------------------------

def generate_unsubscribe_token(email):
    """Return a permanent HMAC-SHA256 token for the given email address."""
    secret = app.config['SECRET_KEY'].encode()
    return hmac.new(secret, email.lower().strip().encode(), hashlib.sha256).hexdigest()

def send_unsubscribe_notification(email):
    """Email NOTIFY_EMAIL to say someone unsubscribed. Silently skips if not configured."""
    if not MAIL_USERNAME or not MAIL_PASSWORD or not NOTIFY_EMAIL:
        return
    try:
        msg = MIMEText(
            f"{email} has unsubscribed from Theatre Aurora emails.\n\n"
            f"To re-add them, go to the Our People page and use the "
            f"Re-subscribe button at the bottom."
        )
        msg['Subject'] = f"Theatre Aurora: Unsubscribe — {email}"
        msg['From'] = MAIL_USERNAME
        msg['To'] = NOTIFY_EMAIL
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"[Theatre_Info] Notification email failed: {e}", file=sys.stderr)


@app.route('/unsubscribe', methods=['GET', 'POST'])
def unsubscribe_page():
    """Public unsubscribe page — no login required."""
    db = mysql.connector.connect(
        host=MYSQL_HOST, user=MYSQL_USER,
        password=MYSQL_PASSWORD, database=MYSQL_DATABASE
    )
    cursor = db.cursor()

    # --- One-click via link: /unsubscribe?email=x&token=y ---
    email_param = request.args.get('email', '').strip().lower()
    token_param = request.args.get('token', '')
    if email_param and token_param:
        expected = generate_unsubscribe_token(email_param)
        if hmac.compare_digest(token_param, expected):
            cursor.execute(
                "INSERT IGNORE INTO Unsubscribed (email) VALUES (%s)", (email_param,)
            )
            db.commit()
            new_entry = cursor.rowcount > 0
            db.close()
            if new_entry:
                send_unsubscribe_notification(email_param)
            return render_template('unsubscribe.html',
                confirmed=True, already=not new_entry, email=email_param)
        db.close()
        return render_template('unsubscribe.html', error=True)

    # --- Form submission ---
    if request.method == 'POST':
        email_form = request.form.get('email', '').strip().lower()
        if email_form:
            cursor.execute(
                "INSERT IGNORE INTO Unsubscribed (email) VALUES (%s)", (email_form,)
            )
            db.commit()
            new_entry = cursor.rowcount > 0
            db.close()
            if new_entry:
                send_unsubscribe_notification(email_form)
            return render_template('unsubscribe.html',
                confirmed=True, already=not new_entry, email=email_form)
        db.close()
        return render_template('unsubscribe.html', error_empty=True)

    db.close()
    return render_template('unsubscribe.html', prefill=email_param)


@app.route('/resubscribe', methods=['POST'])
@login_required
def resubscribe():
    """Admin-only: remove someone from the Unsubscribed table."""
    email = request.form.get('email', '').strip().lower()
    if email:
        db = mysql.connector.connect(
            host=MYSQL_HOST, user=MYSQL_USER,
            password=MYSQL_PASSWORD, database=MYSQL_DATABASE
        )
        cursor = db.cursor()
        cursor.execute("DELETE FROM Unsubscribed WHERE email = %s", (email,))
        db.commit()
        db.close()
    return redirect(url_for('OurPeople'))


# ---------------------------------------------------------------------------

@app.route('/OurPeople')
@login_required
def OurPeople():
    db = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE
    )
    cursor = db.cursor()

    # Get all patrons who have role data ( // in Notes) or are on the Volunteers mailing list
    cursor.execute("""
        SELECT First_name, Last_name, Email, Notes, Marketing_Lists
        FROM Patrons
        WHERE Notes LIKE '%//%'
           OR Marketing_Lists LIKE '%Volunteers%'
        ORDER BY Last_name, First_name
    """)
    rows = cursor.fetchall()

    # Get show-to-season mapping from Ticket_Info
    cursor.execute("""
        SELECT DISTINCT Show_name, Season
        FROM Ticket_Info
        ORDER BY Season DESC, Show_name
    """)
    ticket_shows = cursor.fetchall()

    # Get last update time
    cursor.execute("SELECT Update_date_time FROM Updates ORDER BY Update_date_time DESC LIMIT 1")
    update_data = cursor.fetchall()
    last_update = update_data[0][0] if update_data else None
    formatted_update = last_update.strftime('%B %-d, %Y at %-I:%M %p') if last_update else 'Not available'

    # Get unsubscribed emails
    cursor.execute("SELECT email, unsubscribed_date FROM Unsubscribed ORDER BY unsubscribed_date DESC")
    unsubscribed_rows = cursor.fetchall()
    unsubscribed_emails = {r[0].lower().strip() for r in unsubscribed_rows}
    unsubscribed_list = [{'email': r[0], 'date': r[1].strftime('%B %-d, %Y') if r[1] else ''} for r in unsubscribed_rows]

    db.close()

    # Build a lookup: show name -> season label
    # Use case-insensitive, substring matching for fuzzy matching
    show_season_map = {}
    for ticket_show, season in ticket_shows:
        show_season_map[ticket_show] = season

    def get_season_label(season_date):
        """Convert a season start date (e.g. 2024-07-01) to '2024-2025'."""
        if isinstance(season_date, str):
            from dateutil.parser import parse
            season_date = parse(season_date)
        year = season_date.year
        month = season_date.month
        if month >= 7:
            return f"{year}-{year + 1}"
        else:
            return f"{year - 1}-{year}"

    def find_season_for_show(show_name):
        """Match a show name from Notes to a season via Ticket_Info."""
        show_lower = show_name.lower()
        # Exact match first
        for ticket_show, season in show_season_map.items():
            if ticket_show.lower() == show_lower:
                return get_season_label(season)
        # Substring match (Notes show name contained in Ticket_Info name or vice versa)
        for ticket_show, season in show_season_map.items():
            if show_lower in ticket_show.lower() or ticket_show.lower() in show_lower:
                return get_season_label(season)
        return "Other"

    # Parse Notes into structured role data — one row per person, all roles combined
    table_rows = []
    all_roles = set()
    all_shows = set()
    show_to_season = {}

    for first_name, last_name, email, notes, marketing_lists in rows:
        roles = []
        if notes:
            for line in notes.split('\n'):
                if '//' in line:
                    parts = line.split('//', 1)
                    show = parts[0].strip()
                    role = parts[1].strip()
                    season = find_season_for_show(show)
                    roles.append({'show': show, 'role': role})
                    all_roles.add(role)
                    all_shows.add(show)
                    show_to_season[show] = season
        ml = marketing_lists or ''
        is_volunteer = 'Volunteers' in [item.strip() for item in ml.split(';')]
        email_clean = (email or '').strip().lower()
        is_unsubscribed = email_clean in unsubscribed_emails
        if roles or is_volunteer:
            table_rows.append({
                'first_name': first_name or '',
                'last_name': last_name or '',
                'email': email or '',
                'roles': roles,
                'all_roles': ','.join(r['role'] for r in roles),
                'all_shows': ','.join(r['show'] for r in roles),
                'is_volunteer': is_volunteer,
                'is_unsubscribed': is_unsubscribed,
                'unsubscribe_token': generate_unsubscribe_token(email_clean) if email_clean else '',
            })

    # Sort by last name, first name
    table_rows.sort(key=lambda r: (r['last_name'].lower(), r['first_name'].lower()))

    # Group shows by season, sorted with most recent season first
    seasons = {}
    for show, season in show_to_season.items():
        if season not in seasons:
            seasons[season] = []
        seasons[season].append(show)
    for season in seasons:
        seasons[season].sort()
    sorted_seasons = sorted(seasons.keys(), reverse=True)
    shows_by_season = [(s, seasons[s]) for s in sorted_seasons]

    return render_template('OurPeople.html',
        table_rows=table_rows,
        all_roles=sorted(all_roles),
        shows_by_season=shows_by_season,
        formatted_update=formatted_update,
        unsubscribed_list=unsubscribed_list,
    )


if __name__ == '__main__':
    app.run(debug=True)
