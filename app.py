from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pymysql
import requests
import os
import traceback
import secrets
import smtplib
import re
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, formatdate
from datetime import datetime, timedelta, timezone

try:
    from flask_mail import Mail, Message
except ImportError:
    Mail = None
    Message = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def load_local_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if load_dotenv:
        load_dotenv(dotenv_path=env_path, override=True)
        return

    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, 'r', encoding='utf-8') as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except Exception as e:
        print(f"[Env Debug] Unable to load .env file: {e}")


load_local_env()

OTP_EXPIRY_MINUTES = 10
GMAIL_SMTP_SERVER = 'smtp.gmail.com'
GMAIL_SMTP_PORT = 587

PHONEPE_CLIENT_ID = os.getenv('PHONEPE_CLIENT_ID', '')
PHONEPE_CLIENT_SECRET = os.getenv('PHONEPE_CLIENT_SECRET', '')
PHONEPE_CLIENT_VERSION = os.getenv('PHONEPE_CLIENT_VERSION', '1')
PHONEPE_BASE_URL = os.getenv('PHONEPE_BASE_URL', 'https://api-preprod.phonepe.com/apis/pg-sandbox').rstrip('/')
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_app_secret_key():
    configured_secret = os.getenv('SECRET_KEY')
    if configured_secret:
        return configured_secret

    local_secret_path = os.path.join(BASE_DIR, '.skillflow_secret_key')
    try:
        if os.path.exists(local_secret_path):
            with open(local_secret_path, 'r', encoding='utf-8') as secret_file:
                local_secret = secret_file.read().strip()
                if local_secret:
                    return local_secret

        local_secret = secrets.token_urlsafe(48)
        with open(local_secret_path, 'w', encoding='utf-8') as secret_file:
            secret_file.write(local_secret)
        return local_secret
    except OSError:
        print('[Config Warning] Unable to persist local SECRET_KEY. Admin sessions may reset after server restart.')
        return secrets.token_urlsafe(48)

app = Flask(__name__, template_folder='templates', static_folder='static', static_url_path='/static')
app.secret_key = load_app_secret_key()
if not os.getenv('SECRET_KEY'):
    print('[Config Warning] SECRET_KEY is not set. Using a persistent local development key.')
app.permanent_session_lifetime = timedelta(days=3650)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=PUBLIC_BASE_URL.startswith('https://'),
    SESSION_REFRESH_EACH_REQUEST=True,
    MAX_CONTENT_LENGTH=12 * 1024 * 1024,
)
app.config['MAIL_SERVER'] = GMAIL_SMTP_SERVER
app.config['MAIL_PORT'] = GMAIL_SMTP_PORT
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME'])
app.config['MAIL_SUPPRESS_SEND'] = False
mail = Mail(app) if Mail else None
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'SkillFlow@123')
if not os.getenv('ADMIN_PASSWORD'):
    print('[Config Warning] ADMIN_PASSWORD is not set. Using the development default password.')
ADMIN_EMAIL = 'skillflowadmin@gmail.com'
ADMIN_SESSION_HOURS = 24
ADMIN_SESSION_VERSION = 'skillflow-admin-session-v2'

USER_SESSION_KEYS = {
    'user_id',
    'username',
    'user_session_version',
    'user_remember_login',
    'pending_verification_email',
    'pending_verification_user_id',
    'password_reset_user_id',
    'password_reset_email',
    'login_nonce',
}

ADMIN_SESSION_KEYS = {
    'admin_logged_in',
    'admin_id',
    'admin_username',
    'admin_name',
    'admin_login_time',
    'admin_session_version',
    'admin_login_nonce',
}

RATE_LIMIT_BUCKETS = {}
CSRF_EXEMPT_ENDPOINTS = {'static', 'verify_payment'}


def get_csrf_token():
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['csrf_token'] = token
    return token


def csrf_error_response():
    message = 'Invalid security token. Refresh the page and try again.'
    if request.path.startswith('/api/') or request.is_json or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': False, 'error': message}), 403
    flash(message, 'error')
    return redirect(request.referrer or url_for('auth_page'))


def is_csrf_valid():
    expected = session.get('csrf_token')
    supplied = (
        request.headers.get('X-CSRFToken')
        or request.headers.get('X-CSRF-Token')
        or request.form.get('csrf_token')
    )
    if not supplied and request.is_json:
        supplied = (request.get_json(silent=True) or {}).get('csrf_token')
    return bool(expected and supplied and secrets.compare_digest(str(expected), str(supplied)))


def is_rate_limited(action, limit=8, window_seconds=300):
    now = time.time()
    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
    key = f'{action}:{ip_address}'
    attempts = [stamp for stamp in RATE_LIMIT_BUCKETS.get(key, []) if now - stamp < window_seconds]
    if len(attempts) >= limit:
        RATE_LIMIT_BUCKETS[key] = attempts
        return True
    attempts.append(now)
    RATE_LIMIT_BUCKETS[key] = attempts
    return False


def clear_user_session_state():
    # Fix: prevent stale browser sessions from opening a previous user's account.
    for key in USER_SESSION_KEYS:
        session.pop(key, None)


def clear_pending_verification_state():
    session.pop('pending_verification_email', None)
    session.pop('pending_verification_user_id', None)


def start_user_session(user, remember=False):
    # Keep admin and user session keys separate.
    clear_user_session_state()
    session.permanent = bool(remember)
    session['user_id'] = int(user['id'])
    session['username'] = user['username']
    session['user_session_version'] = int(user.get('user_session_version') or 1)
    session['user_remember_login'] = bool(remember)
    session['login_nonce'] = secrets.token_urlsafe(16)


def start_admin_session(username, admin_id=0, full_name='Admin'):
    # Keep admin and user session keys separate.
    for key in ADMIN_SESSION_KEYS:
        session.pop(key, None)
    session.permanent = False
    session['admin_logged_in'] = True
    session['admin_id'] = admin_id or 0
    session['admin_username'] = username
    session['admin_name'] = full_name or 'Admin'
    session['admin_login_time'] = datetime.now(timezone.utc).isoformat()
    session['admin_session_version'] = ADMIN_SESSION_VERSION
    session['admin_login_nonce'] = secrets.token_urlsafe(16)


PROJECT_DIR = os.path.dirname(BASE_DIR)
WORKSPACE_DIR = os.path.dirname(PROJECT_DIR)
AVATAR_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg')
AVATAR_STATIC_FOLDER = 'images/avatars'
AVATAR_CLEAN_NAMES = [
    'noor', 'mia', 'lila', 'zia', 'aria', 'nia', 'sia', 'yara', 'kira', 'elia',
    'luna', 'eva', 'mira', 'ria', 'zara', 'leya', 'anya', 'isla', 'nova', 'mirae',
    'ayla', 'lina', 'fia', 'nyra', 'suzi', 'hana', 'inna', 'rumi', 'mira2', 'sana',
    'alia', 'mona', 'naya', 'roya', 'tia', 'vivi', 'ema', 'yumi', 'lora', 'sira',
    'leo', 'max', 'zayn', 'noah', 'eli', 'theo', 'omar', 'zed', 'rio', 'kai',
    'liam', 'ezra', 'milo', 'aron', 'ivo', 'luca', 'niko', 'enzo', 'sam', 'ray',
    'evan', 'alan', 'ian', 'ben', 'neo', 'zak', 'alex', 'dean', 'jude', 'cole',
    'adam', 'noel', 'rian', 'levi', 'ace', 'remy', 'ayan', 'dani', 'kian', 'jax',
]
AVATAR_CLEAN_FILENAMES = [f'{name}.png' for name in AVATAR_CLEAN_NAMES]
AVATAR_DISPLAY_NAMES = {
    'mira2.png': 'Mira',
}
AVATAR_DIR_CANDIDATES = [
    os.path.join(BASE_DIR, 'static', AVATAR_STATIC_FOLDER),
    os.path.join(BASE_DIR, 'static', 'avatar'),
    os.path.join(PROJECT_DIR, 'avatar'),
    os.path.join(PROJECT_DIR, 'avtar'),
    os.path.join(WORKSPACE_DIR, 'avatar'),
    os.path.join(WORKSPACE_DIR, 'avtar'),
]


def get_phonepe_runtime_config():
    config = {
        'client_id': PHONEPE_CLIENT_ID,
        'client_secret': PHONEPE_CLIENT_SECRET,
        'client_version': PHONEPE_CLIENT_VERSION or '1',
        'merchant_id': os.getenv('PHONEPE_MERCHANT_ID', ''),
        'payment_mode': os.getenv('PHONEPE_PAYMENT_MODE', 'test').lower(),
        'base_url': PHONEPE_BASE_URL or 'https://api-preprod.phonepe.com/apis/pg-sandbox',
    }

    # Payment code can use credentials saved from admin settings without exposing them to the frontend.
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                if table_exists(cursor, 'admin_settings'):
                    cursor.execute(
                        "SELECT setting_key, setting_value FROM admin_settings WHERE setting_key IN (%s, %s, %s, %s, %s, %s)",
                        ('phonepe_client_id', 'phonepe_client_secret', 'phonepe_client_version', 'phonepe_base_url', 'phonepe_merchant_id', 'phonepe_payment_mode')
                    )
                    settings = {row['setting_key']: row['setting_value'] for row in cursor.fetchall()}
                    config['client_id'] = config['client_id'] or settings.get('phonepe_client_id', '')
                    config['client_secret'] = config['client_secret'] or settings.get('phonepe_client_secret', '')
                    config['client_version'] = config['client_version'] or settings.get('phonepe_client_version', '1')
                    config['merchant_id'] = config['merchant_id'] or settings.get('phonepe_merchant_id', '')
                    config['payment_mode'] = (settings.get('phonepe_payment_mode') or config['payment_mode'] or 'test').lower()
                    config['base_url'] = (settings.get('phonepe_base_url') or config['base_url']).rstrip('/')
        except Exception as e:
            print(f"[PhonePe Config Debug] Unable to read DB PhonePe settings: {e}")
            traceback.print_exc()
        finally:
            conn.close()

    config['base_url'] = (config.get('base_url') or '').rstrip('/')
    if config.get('payment_mode') == 'live' and not os.getenv('PHONEPE_BASE_URL'):
        config['base_url'] = 'https://api.phonepe.com/apis/pg'
    return config


def get_phonepe_access_token(config=None):
    config = config or get_phonepe_runtime_config()
    client_id = config.get('client_id') or ''
    client_secret = config.get('client_secret') or ''
    client_version = config.get('client_version') or ''
    base_url = config.get('base_url') or ''

    if not client_id or not client_secret or not client_version or not base_url:
        print(
            "[PhonePe Config Error] Missing config:",
            {
                'PHONEPE_CLIENT_ID': bool(client_id),
                'PHONEPE_CLIENT_SECRET': bool(client_secret),
                'PHONEPE_CLIENT_VERSION': bool(client_version),
                'PHONEPE_BASE_URL': bool(base_url),
            }
        )
        raise RuntimeError('PhonePe credentials are not configured. Set PHONEPE_CLIENT_ID and PHONEPE_CLIENT_SECRET.')

    # PhonePe API request: exchange backend-only client credentials for a sandbox access token.
    token_payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'client_version': client_version,
        'grant_type': 'client_credentials',
    }
    print("[PhonePe Token Request]", {
        'url': f'{base_url}/v1/oauth/token',
        'client_id_loaded': bool(client_id),
        'client_secret_loaded': bool(client_secret),
        'client_version': client_version,
    })
    response = requests.post(
        f'{base_url}/v1/oauth/token',
        data=token_payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        timeout=20,
    )
    print("PhonePe Token Status:", response.status_code)
    if not response.ok:
        print("PhonePe Token Response:", response.text)
    response.raise_for_status()
    token_response = response.json()
    # PhonePe API response: accept common token field names across sandbox responses.
    token = token_response.get('access_token') or token_response.get('accessToken')
    if not token:
        raise RuntimeError('PhonePe access token missing in response')
    return token


def phonepe_config_snapshot():
    config = get_phonepe_runtime_config()
    return {
        'client_id_loaded': bool(config.get('client_id')),
        'client_secret_loaded': bool(config.get('client_secret')),
        'client_version_loaded': bool(config.get('client_version')),
        'merchant_id_loaded': bool(config.get('merchant_id')),
        'payment_mode': config.get('payment_mode'),
        'base_url_loaded': bool(config.get('base_url')),
        'base_url': config.get('base_url'),
        'public_base_url_loaded': bool(PUBLIC_BASE_URL),
    }


def extract_phonepe_redirect_url(payment_response):
    return (
        payment_response.get('redirectUrl')
        or payment_response.get('paymentUrl')
        or payment_response.get('url')
        or payment_response.get('data', {}).get('redirectUrl')
        or payment_response.get('data', {}).get('instrumentResponse', {}).get('redirectInfo', {}).get('url')
    )


def extract_phonepe_payment_id(status_response):
    payment_details = status_response.get('paymentDetails') or status_response.get('data', {}).get('paymentDetails') or []
    if payment_details:
        return payment_details[0].get('transactionId') or payment_details[0].get('paymentId')
    return (
        status_response.get('transactionId')
        or status_response.get('paymentId')
        or status_response.get('orderId')
        or status_response.get('data', {}).get('transactionId')
    )


def extract_phonepe_payment_state(status_response):
    return (
        status_response.get('state')
        or status_response.get('status')
        or status_response.get('code')
        or status_response.get('data', {}).get('state')
        or status_response.get('data', {}).get('status')
    )


def is_phonepe_success_state(payment_state):
    return str(payment_state or '').upper() in ('COMPLETED', 'SUCCESS', 'PAYMENT_SUCCESS')


def is_development_mode():
    return app.debug or os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_DEBUG') == '1'


def phonepe_error_response(message, status_code=500, **details):
    payload = {'error': message}
    safe_details = {key: value for key, value in details.items() if value is not None}
    if safe_details:
        payload['details'] = safe_details
    return jsonify(payload), status_code


def get_avatar_dir():
    for path in AVATAR_DIR_CANDIDATES:
        if os.path.isdir(path):
            return path
    return AVATAR_DIR_CANDIDATES[0]


def get_avatar_filenames():
    avatar_dir = get_avatar_dir()
    if not os.path.isdir(avatar_dir):
        return []
    return [
        filename for filename in AVATAR_CLEAN_FILENAMES
        if os.path.isfile(os.path.join(avatar_dir, filename))
    ]


def get_avatar_options():
    return [
        {
            'name': AVATAR_DISPLAY_NAMES.get(
                filename,
                os.path.splitext(filename)[0].replace('-', ' ').replace('_', ' ').title()
            ),
            'url': url_for('static', filename=f'{AVATAR_STATIC_FOLDER}/{filename}'),
        }
        for filename in get_avatar_filenames()
    ]


def get_default_avatar_url():
    avatars = get_avatar_options()
    return avatars[0]['url'] if avatars else ''


def avatar_url_for_seed(seed):
    avatars = get_avatar_options()
    if not avatars:
        return ''
    value = sum(ord(ch) for ch in (seed or 'skillflow'))
    return avatars[value % len(avatars)]['url']


def normalize_avatar_url(url, seed=None):
    avatar_urls = {avatar['url'] for avatar in get_avatar_options()}
    if url in avatar_urls:
        return url
    return avatar_url_for_seed(seed)


def parse_skill_values(value):
    return [
        skill.strip().lower()
        for skill in (value or '').split(',')
        if skill and skill.strip()
    ]


def skill_lists_overlap(first_value, second_value):
    first_skills = parse_skill_values(first_value)
    second_skills = set(parse_skill_values(second_value))
    return any(skill in second_skills for skill in first_skills)


def is_two_way_match(current_user, other_user):
    return (
        skill_lists_overlap(current_user.get('skills_wanted'), other_user.get('skills_offered'))
        and skill_lists_overlap(other_user.get('skills_wanted'), current_user.get('skills_offered'))
    )


def skill_match_percentage(current_user, other_user):
    """Return a percentage based only on real teach/want skill overlap."""
    current_offered = set(parse_skill_values(current_user.get('skills_offered')))
    current_wanted = set(parse_skill_values(current_user.get('skills_wanted')))
    other_offered = set(parse_skill_values(other_user.get('skills_offered')))
    other_wanted = set(parse_skill_values(other_user.get('skills_wanted')))

    total_compared = len(current_wanted) + len(other_wanted)
    if total_compared == 0:
        return 0

    matched_skills = len(current_offered.intersection(other_wanted))
    matched_skills += len(other_offered.intersection(current_wanted))
    return round((matched_skills / total_compared) * 100)


def skill_match_status(current_user, other_user):
    percentage = skill_match_percentage(current_user, other_user)
    if percentage == 100:
        return 'Full Match'
    if percentage > 0:
        return 'Partial Match'
    return 'No Match'


def skill_match_pairs(current_user, other_user):
    current_offered = set(parse_skill_values(current_user.get('skills_offered')))
    current_wanted = set(parse_skill_values(current_user.get('skills_wanted')))
    other_offered = set(parse_skill_values(other_user.get('skills_offered')))
    other_wanted = set(parse_skill_values(other_user.get('skills_wanted')))

    pairs = []
    for skill in sorted(current_wanted.intersection(other_offered)):
        display_skill = skill.title()
        pairs.append({
            'your_skill': display_skill,
            'their_skill': display_skill,
            'direction': 'they_teach_you',
            'label': f'You want {display_skill}; they offer {display_skill}'
        })
    for skill in sorted(current_offered.intersection(other_wanted)):
        display_skill = skill.title()
        pairs.append({
            'your_skill': display_skill,
            'their_skill': display_skill,
            'direction': 'you_teach_them',
            'label': f'You offer {display_skill}; they want {display_skill}'
        })
    return pairs


def enrich_skill_match(current_user, other_user):
    percentage = skill_match_percentage(current_user, other_user)
    match_pairs = skill_match_pairs(current_user, other_user)
    return {
        'match_percentage': percentage,
        'match_status': skill_match_status(current_user, other_user),
        'match_badge_variant': match_badge_variant(percentage),
        'match_badge_label': match_badge_label(percentage),
        'match_pairs': match_pairs,
        'match_summary': match_pairs[0]['label'] if match_pairs else match_badge_label(percentage)
    }


def match_badge_variant(percentage):
    if percentage >= 100:
        return 'full'
    if percentage > 0:
        return 'partial'
    return 'none'


def match_badge_label(percentage):
    return f'{percentage}% Match'



# Database connection configuration
def get_db_connection():
    try:
        connection = pymysql.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            user=os.getenv('DB_USER', 'root'),
            password=os.getenv('DB_PASSWORD', ''),
            database=os.getenv('DB_NAME', 'skillflow_db'),
            cursorclass=pymysql.cursors.DictCursor
        )

            
        return connection
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None


def transform_timestamp(value):
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%dT%H:%M:%S')
    return value


USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_.]{3,25}$')
EMAIL_PATTERN = re.compile(r'^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$', re.IGNORECASE)
DISPOSABLE_EMAIL_DOMAINS = {
    '10minutemail.com', '10minutemail.net', '10minutemail.org', '20minutemail.com',
    'guerrillamail.com', 'guerrillamail.net', 'guerrillamail.org', 'guerrillamail.de',
    'yopmail.com', 'yopmail.fr', 'yopmail.net',
    'mailinator.com', 'mailinator.net', 'mailinator.org',
    'tempmail.com', 'temp-mail.org', 'temp-mail.io', 'tempmailo.com',
    'fakemail.net', 'fakemailgenerator.com', 'fakeinbox.com',
    'throwawaymail.com', 'throwawaymail.net', 'trashmail.com', 'trashmail.net',
    'maildrop.cc', 'getnada.com', 'sharklasers.com', 'grr.la', 'guerrillamailblock.com',
    'dispostable.com', 'moakt.com', 'emailondeck.com', 'mailnesia.com',
}
DISPOSABLE_EMAIL_KEYWORDS = (
    'tempmail', 'temp-mail', '10minutemail', 'guerrillamail', 'yopmail',
    'mailinator', 'fakemail', 'throwawaymail', 'trashmail', 'disposable',
)


def normalize_username(value):
    return (value or '').strip().lower()


def username_validation_error(username):
    if not username:
        return None
    if len(username) < 3 or len(username) > 25:
        return 'Username must be 3 to 25 characters.'
    if not USERNAME_PATTERN.fullmatch(username):
        return 'Username can only use letters, numbers, underscore, and dot.'
    return None


def is_username_available(cursor, username, exclude_user_id=None):
    username = normalize_username(username)
    if exclude_user_id:
        cursor.execute(
            "SELECT id FROM users WHERE LOWER(username) = LOWER(%s) AND id != %s LIMIT 1",
            (username, exclude_user_id)
        )
    else:
        cursor.execute(
            "SELECT id FROM users WHERE LOWER(username) = LOWER(%s) LIMIT 1",
            (username,)
        )
    return not cursor.fetchone()


def generate_unique_username(cursor, full_name=''):
    cleaned_name = re.sub(r'[^A-Za-z0-9_]+', '_', (full_name or '').strip().lower()).strip('_')
    base_options = [
        cleaned_name[:16] if len(cleaned_name) >= 3 else '',
        'skill_user',
        'coder',
    ]
    for base in [option for option in base_options if option]:
        for _ in range(12):
            candidate = f"{base}_{secrets.randbelow(900) + 100}"
            if len(candidate) <= 25 and is_username_available(cursor, candidate):
                return candidate

    while True:
        candidate = f"skill_user_{secrets.randbelow(9000) + 1000}"
        if len(candidate) <= 25 and is_username_available(cursor, candidate):
            return candidate


def normalize_email(value):
    return (value or '').strip().lower()


def email_validation_error(email):
    if not email:
        return 'Email is required.'
    if len(email) > 190 or not EMAIL_PATTERN.fullmatch(email):
        return 'Please enter a valid email address.'
    return None


def email_domain(email):
    return email.rsplit('@', 1)[-1].strip().lower() if '@' in email else ''


def is_disposable_email(email):
    domain = email_domain(email)
    if not domain:
        return False
    if domain in DISPOSABLE_EMAIL_DOMAINS:
        return True
    return any(keyword in domain for keyword in DISPOSABLE_EMAIL_KEYWORDS)


def log_disposable_email_attempt(cursor, email, source='registration'):
    ensure_email_security_schema(cursor)
    cursor.execute(
        """
        INSERT INTO disposable_email_attempts (email, domain, source, ip_address, user_agent, created_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        """,
        (
            email,
            email_domain(email),
            source,
            request.headers.get('X-Forwarded-For', request.remote_addr or '')[:80],
            (request.headers.get('User-Agent') or '')[:255],
        )
    )


def generate_verification_otp():
    return f'{secrets.randbelow(1000000):06d}'


def verification_expiry_timestamp(expiry_value):
    if isinstance(expiry_value, datetime):
        return int(expiry_value.timestamp() * 1000)
    return None


def get_verification_cooldown_seconds(cursor):
    if table_exists(cursor, 'admin_settings'):
        cursor.execute("SELECT setting_value FROM admin_settings WHERE setting_key = 'resend_otp_cooldown' LIMIT 1")
        row = cursor.fetchone()
        try:
            return max(0, int(row['setting_value'])) if row and row.get('setting_value') else 60
        except (TypeError, ValueError):
            return 60
    return 60


def can_send_verification_email(user, cooldown_seconds):
    last_sent = user.get('verification_last_sent_at') if user else None
    if not isinstance(last_sent, datetime) or cooldown_seconds <= 0:
        return True, 0
    elapsed = (datetime.now() - last_sent).total_seconds()
    remaining = max(0, int(cooldown_seconds - elapsed))
    return remaining <= 0, remaining


def send_verification_email(to_email, otp):
    config, missing = get_smtp_config()
    if missing:
        print(f"[Email Verification Error] SMTP is not fully configured. Missing: {', '.join(missing)}.")
        return False

    body = (
        f'Your SkillFlow email verification OTP is: {otp}\n\n'
        f'This code will expire in {OTP_EXPIRY_MINUTES} minutes.\n\n'
        'If you did not create a SkillFlow account, please ignore this email.'
    )

    try:
        if mail and Message:
            message = Message(
                subject='Verify your SkillFlow email',
                sender=config['sender'],
                recipients=[to_email],
                body=body
            )
            mail.send(message)
        else:
            message = EmailMessage()
            message['Subject'] = 'Verify your SkillFlow email'
            message['From'] = formataddr(('SkillFlow', config['sender']))
            message['To'] = to_email
            message['Date'] = formatdate(localtime=True)
            message['Message-ID'] = make_msgid(domain='skillflow.local')
            message['Reply-To'] = config['sender']
            message.set_content(body)

            with smtplib.SMTP(config['server'], config['port'], timeout=20) as smtp:
                smtp.ehlo()
                if config['use_tls']:
                    smtp.starttls()
                    smtp.ehlo()
                smtp.login(config['username'], config['password'])
                refused_recipients = smtp.send_message(message)
            if refused_recipients:
                print(f"[Email Verification Error] SMTP refused recipients: {refused_recipients}")
                return False
        return True
    except Exception as e:
        print(f"[Email Verification Error] Unable to send verification OTP to {to_email}: {e}")
        traceback.print_exc()
        return False


def issue_verification_otp(cursor, user_id, email):
    otp = generate_verification_otp()
    expiry = datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    cursor.execute(
        """
        UPDATE users
        SET verification_otp = %s,
            verification_expiry = %s,
            verification_last_sent_at = NOW()
        WHERE id = %s
        """,
        (otp, expiry, user_id)
    )
    return otp, expiry


def get_admin_config(cursor):
    ensure_admin_schema(cursor)
    admin_account = get_admin_account(cursor)
    cursor.execute("SELECT setting_key, setting_value FROM admin_settings")
    settings = {row['setting_key']: row['setting_value'] for row in cursor.fetchall()}
    return {
        'platform_name': settings.get('platform_name', 'SkillFlow'),
        'admin_username': admin_account['username'] if admin_account else settings.get('admin_username', ADMIN_USERNAME),
        'admin_email': admin_account['email'] if admin_account else ADMIN_EMAIL,
        'admin_password_hash': admin_account['password'] if admin_account else settings.get('admin_password_hash', generate_password_hash(ADMIN_PASSWORD)),
        'phonepe_client_id': settings.get('phonepe_client_id', PHONEPE_CLIENT_ID),
        'phonepe_client_secret': settings.get('phonepe_client_secret', PHONEPE_CLIENT_SECRET),
        'phonepe_merchant_id': settings.get('phonepe_merchant_id', ''),
        'phonepe_payment_mode': settings.get('phonepe_payment_mode', 'test'),
        'platform_logo': settings.get('platform_logo', ''),
        'website_tagline': settings.get('website_tagline', 'Learn. Swap. Grow.'),
        'maintenance_mode': settings.get('maintenance_mode', 'off'),
        'chat_unlock_price': settings.get('chat_unlock_price', '99'),
        'currency': settings.get('currency', 'INR'),
        'sender_email': settings.get('sender_email', app.config.get('MAIL_DEFAULT_SENDER', '')),
        'smtp_host': settings.get('smtp_host', app.config.get('MAIL_SERVER', GMAIL_SMTP_SERVER)),
        'smtp_port': settings.get('smtp_port', str(app.config.get('MAIL_PORT', GMAIL_SMTP_PORT))),
        'otp_expiry_time': settings.get('otp_expiry_time', str(OTP_EXPIRY_MINUTES)),
        'resend_otp_cooldown': settings.get('resend_otp_cooldown', '60'),
        'session_timeout': settings.get('session_timeout', str(ADMIN_SESSION_HOURS)),
        'user_registration_enabled': settings.get('user_registration_enabled', 'on'),
        'email_notifications_enabled': settings.get('email_notifications_enabled', 'on'),
        'admin_alerts_enabled': settings.get('admin_alerts_enabled', 'on'),
        'payment_notifications_enabled': settings.get('payment_notifications_enabled', 'on'),
        'appearance_mode': settings.get('appearance_mode', 'light'),
        'primary_theme_color': settings.get('primary_theme_color', '#2563EB'),
        'accent_color': settings.get('accent_color', '#22C55E'),
        'last_backup_time': settings.get('last_backup_time', 'No backup recorded yet'),
    }


def save_admin_setting(cursor, key, value):
    cursor.execute(
        """
        INSERT INTO admin_settings (setting_key, setting_value, updated_at)
        VALUES (%s, %s, NOW())
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value), updated_at = NOW()
        """,
        (key, value)
    )


def get_admin_account(cursor, email=None, username=None):
    if not table_exists(cursor, 'admin_accounts'):
        return None
    if email:
        cursor.execute("SELECT * FROM admin_accounts WHERE LOWER(email) = LOWER(%s) LIMIT 1", (email,))
    elif username:
        cursor.execute("SELECT * FROM admin_accounts WHERE username = %s LIMIT 1", (username,))
    else:
        cursor.execute("SELECT * FROM admin_accounts ORDER BY id ASC LIMIT 1")
    return cursor.fetchone()


def generate_admin_reset_code():
    return f'{secrets.randbelow(1000000):06d}'


def get_smtp_config():
    mail_username = (app.config.get('MAIL_USERNAME') or '').strip()
    mail_password = app.config.get('MAIL_PASSWORD') or ''
    mail_sender = (app.config.get('MAIL_DEFAULT_SENDER') or mail_username).strip()

    config = {
        'server': app.config['MAIL_SERVER'],
        'port': app.config['MAIL_PORT'],
        'use_tls': app.config['MAIL_USE_TLS'],
        'username': mail_username,
        'password': mail_password,
        'sender': mail_sender,
    }

    missing = []
    if not config['username']:
        missing.append('MAIL_USERNAME')
    if not config['password']:
        missing.append('MAIL_PASSWORD')
    if not config['sender']:
        missing.append('MAIL_DEFAULT_SENDER or MAIL_USERNAME')
    return config, missing


def send_reset_email(to_email, reset_code, subject, account_label):
    config, missing = get_smtp_config()
    if missing:
        print(f"[{account_label} Reset Email Error] SMTP is not fully configured. Missing: {', '.join(missing)}.")
        return False

    body = (
        f'Your SkillFlow password reset OTP is: {reset_code}\n\n'
        f'This code will expire in {OTP_EXPIRY_MINUTES} minutes.\n\n'
        'If you did not request this password reset, please ignore this email.'
    )

    print(f"[{account_label} Reset Email] Connecting to {config['server']}:{config['port']} with TLS for {to_email}")

    try:
        if mail and Message:
            message = Message(
                subject=subject,
                sender=config['sender'],
                recipients=[to_email],
                body=body
            )
            mail.send(message)
        else:
            message = EmailMessage()
            message['Subject'] = subject
            message['From'] = formataddr(('SkillFlow', config['sender']))
            message['To'] = to_email
            message['Date'] = formatdate(localtime=True)
            message['Message-ID'] = make_msgid(domain='skillflow.local')
            message['Reply-To'] = config['sender']
            message.set_content(body)

            with smtplib.SMTP(config['server'], config['port'], timeout=20) as smtp:
                smtp.ehlo()
                if config['use_tls']:
                    smtp.starttls()
                    smtp.ehlo()
                smtp.login(config['username'], config['password'])
                refused_recipients = smtp.send_message(message)

            if refused_recipients:
                print(f"[{account_label} Reset Email Error] SMTP refused recipients: {refused_recipients}")
                return False

        print(f"[{account_label} Reset Email] Mail send completed for {to_email}. Ask the user to check Inbox, Spam, and Promotions.")
        return True
    except smtplib.SMTPException as e:
        print(f"[{account_label} Reset Email SMTP Error] Unable to send OTP to {to_email}: {e}")
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"[{account_label} Reset Email Error] Unable to send OTP to {to_email}: {e}")
        traceback.print_exc()
        return False


def send_admin_reset_email(to_email, reset_code):
    return send_reset_email(to_email, reset_code, 'SkillFlow Admin Password Reset', 'Admin')


def send_user_reset_email(to_email, reset_code):
    return send_reset_email(to_email, reset_code, 'SkillFlow Password Reset', 'User')


def log_admin_action(cursor, admin_name, user_id, action_type, username=None, account_status=None, action_reason=None):
    if table_exists(cursor, 'admin_actions') and not column_exists(cursor, 'admin_actions', 'action_reason'):
        cursor.execute("ALTER TABLE admin_actions ADD COLUMN action_reason TEXT DEFAULT NULL AFTER account_status")
    if username is None and user_id is not None:
        cursor.execute("SELECT username FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        username = row['username'] if row else None
    cursor.execute(
        """
        INSERT INTO admin_actions (user_id, username, action_type, admin_name, account_status, action_reason, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """,
        (user_id, username, action_type, admin_name, account_status, action_reason)
    )
    titles = {
        'block': 'User blocked',
        'unblock': 'User unblocked',
        'delete': 'User deleted',
        'restore': 'User restored',
        'manual_email_verify': 'User verified',
        'logout': 'User logout',
    }
    if admin_name != 'System':
        record_admin_activity(
            cursor,
            admin_name=admin_name,
            action_type=action_type,
            action_title=titles.get(action_type, action_type.replace('_', ' ').title()),
            action_description=f'{titles.get(action_type, action_type)} for @{username or user_id}.' + (f' Reason: {action_reason}' if action_reason else ''),
            target_type='user',
            target_id=user_id,
            target_name=username,
        )


def ensure_admin_activity_schema(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_activity_logs (
            id INT(11) NOT NULL AUTO_INCREMENT,
            admin_id INT(11) DEFAULT NULL,
            admin_name VARCHAR(120) NOT NULL,
            action_type VARCHAR(80) NOT NULL,
            action_title VARCHAR(190) NOT NULL,
            action_description TEXT DEFAULT NULL,
            target_type VARCHAR(80) DEFAULT NULL,
            target_id INT(11) DEFAULT NULL,
            target_name VARCHAR(190) DEFAULT NULL,
            ip_address VARCHAR(80) DEFAULT NULL,
            user_agent VARCHAR(255) DEFAULT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY action_type (action_type),
            KEY admin_name (admin_name),
            KEY created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )


def record_admin_activity(cursor=None, admin=None, admin_name=None, action_type='system', action_title='Admin action',
                          action_description='', target_type=None, target_id=None, target_name=None):
    own_conn = None
    try:
        if cursor is None:
            own_conn = get_db_connection()
            if not own_conn:
                return
            cursor = own_conn.cursor()
        ensure_admin_activity_schema(cursor)
        safe_agent = (request.headers.get('User-Agent') or '')[:255] if request else ''
        cursor.execute(
            """
            INSERT INTO admin_activity_logs
                (admin_id, admin_name, action_type, action_title, action_description, target_type, target_id, target_name, ip_address, user_agent, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                (admin or {}).get('id') if admin else None,
                admin_name or (admin or {}).get('username') or (admin or {}).get('full_name') or 'Admin',
                action_type,
                action_title,
                action_description,
                target_type,
                target_id,
                target_name,
                request.headers.get('X-Forwarded-For', request.remote_addr) if request else None,
                safe_agent,
            )
        )
        if own_conn:
            own_conn.commit()
    except Exception as e:
        print(f"Admin activity log skipped: {e}")
    finally:
        if own_conn:
            own_conn.close()


DISPUTE_STATUS_LABELS = {
    'pending': 'Pending',
    'under_review': 'Under Review',
    'resolved': 'Resolved',
    'rejected': 'Rejected',
}


def normalize_dispute_status(value):
    normalized = (value or '').strip().lower().replace(' ', '_').replace('-', '_')
    legacy_map = {
        'pending': 'pending',
        'reviewed': 'under_review',
        'under_review': 'under_review',
        'resolved': 'resolved',
        'rejected': 'rejected',
    }
    return legacy_map.get(normalized, 'pending')


def create_admin_notification(cursor, notification_type, title, message, related_id=None, icon='fa-solid fa-bell'):
    ensure_admin_schema(cursor)
    setting_key = None
    if notification_type == 'payment':
        setting_key = 'payment_notifications_enabled'
    elif notification_type == 'system':
        setting_key = 'admin_alerts_enabled'
    if setting_key:
        cursor.execute("SELECT setting_value FROM admin_settings WHERE setting_key = %s LIMIT 1", (setting_key,))
        row = cursor.fetchone()
        if row and row.get('setting_value') == 'off':
            return
    cursor.execute(
        """
        INSERT INTO admin_notifications
            (notification_type, title, message, related_id, icon, is_read, created_at)
        VALUES (%s, %s, %s, %s, %s, FALSE, NOW())
        """,
        (notification_type, title, message, related_id, icon)
    )


def get_admin_unread_notification_count():
    conn = get_db_connection()
    if not conn:
        return 0
    try:
        with conn.cursor() as cursor:
            ensure_admin_schema(cursor)
            cursor.execute("SELECT COUNT(*) AS count FROM admin_notifications WHERE is_read = FALSE")
            row = cursor.fetchone()
            return row['count'] if row else 0
    except Exception as e:
        print(f"Error counting admin notifications: {e}")
        return 0
    finally:
        conn.close()


def get_admin_theme_mode():
    conn = get_db_connection()
    if not conn:
        return 'light'
    try:
        with conn.cursor() as cursor:
            if table_exists(cursor, 'admin_settings'):
                cursor.execute("SELECT setting_value FROM admin_settings WHERE setting_key = 'appearance_mode' LIMIT 1")
                row = cursor.fetchone()
                if row and row.get('setting_value') == 'dark':
                    return 'dark'
    except Exception as e:
        print(f"Error loading admin theme: {e}")
    finally:
        conn.close()
    return 'light'


def get_chat_unlock_price_rupees():
    conn = get_db_connection()
    if not conn:
        return 99.0
    try:
        with conn.cursor() as cursor:
            if table_exists(cursor, 'admin_settings'):
                cursor.execute("SELECT setting_value FROM admin_settings WHERE setting_key = 'chat_unlock_price' LIMIT 1")
                row = cursor.fetchone()
                if row and row.get('setting_value'):
                    return max(float(row['setting_value']), 0.0)
    except Exception as e:
        print(f"Error loading chat unlock price: {e}")
    finally:
        conn.close()
    return 99.0


ENGAGEMENT_BADGES = {
    'first_match': ('First Match', 'fa-solid fa-handshake'),
    'five_skill_chats': ('5 Skill Chats', 'fa-regular fa-message'),
    'seven_day_streak': ('7 Day Streak', 'fa-solid fa-fire'),
    'helpful_user': ('Helpful User', 'fa-solid fa-star'),
    'premium_user': ('Premium User', 'fa-solid fa-crown'),
}

SKILL_CATEGORY_ICONS = {
    'Programming': 'fa-solid fa-code',
    'Web Development': 'fa-solid fa-globe',
    'Python': 'fa-brands fa-python',
    'Java': 'fa-brands fa-java',
    'UI/UX Design': 'fa-solid fa-pen-ruler',
    'Graphic Design': 'fa-solid fa-palette',
    'Video Editing': 'fa-solid fa-video',
    'Digital Marketing': 'fa-solid fa-bullhorn',
    'Cooking': 'fa-solid fa-utensils',
    'Photography': 'fa-solid fa-camera',
    'Language Learning': 'fa-solid fa-language',
    'Music': 'fa-solid fa-music',
    'Fitness': 'fa-solid fa-dumbbell',
    'Public Speaking': 'fa-solid fa-microphone-lines',
    'Content Writing': 'fa-solid fa-pen-nib',
    'AI & Machine Learning': 'fa-solid fa-robot',
    'Cloud Computing': 'fa-solid fa-cloud',
    'Business': 'fa-solid fa-briefcase',
    'Excel & Office Skills': 'fa-solid fa-table-cells',
    'Other Skills': 'fa-solid fa-layer-group',
}


@app.context_processor
def inject_csrf():
    return {'csrf_token': get_csrf_token}


@app.context_processor
def inject_admin_layout_state():
    if not request.path.startswith('/admin') or request.endpoint in ('admin_login_page', 'admin_forgot_password_page'):
        return {}
    return {
        'admin_theme_mode': get_admin_theme_mode(),
        'unread_notification_count': get_admin_unread_notification_count(),
    }


@app.context_processor
def inject_user_nav_state():
    if request.path.startswith('/admin') or not session.get('user_id'):
        return {}
    counts = {'user_nav_unread_count': 0}
    conn = get_db_connection()
    if not conn:
        return counts
    try:
        with conn.cursor() as cursor:
            ensure_engagement_schema(cursor)
            cursor.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM user_notifications WHERE user_id = %s AND is_read = FALSE) AS notifications,
                  (SELECT COUNT(*) FROM messages WHERE receiver_id = %s AND COALESCE(is_read, 0) = 0) AS messages
                """,
                (session['user_id'], session['user_id'])
            )
            row = cursor.fetchone() or {}
            counts['user_nav_unread_count'] = int(row.get('notifications') or 0) + int(row.get('messages') or 0)
    except Exception as e:
        print(f"Error loading user nav counts: {e}")
    finally:
        conn.close()
    return counts


def expire_chat_access(cursor, request_id=None):
    ensure_premium_schema(cursor)
    cursor.execute(
        """
        UPDATE users
        SET is_premium = FALSE
        WHERE is_premium = TRUE
          AND premium_expiry_date IS NOT NULL
          AND premium_expiry_date <= NOW()
        """
    )
    if request_id:
        cursor.execute(
            """
            UPDATE requests
            SET payment_status = 'expired'
            WHERE id = %s AND payment_status = 'paid' AND expiry_date <= NOW()
            """,
            (request_id,)
        )
    else:
        cursor.execute(
            """
            UPDATE requests
            SET payment_status = 'expired'
            WHERE payment_status = 'paid' AND expiry_date <= NOW()
            """
        )


def get_chat_request(cursor, request_id, user_id):
    expire_chat_access(cursor, request_id)
    cursor.execute(
        """
        SELECT r.id, r.sender_id, r.receiver_id, r.status, r.payment_status, r.payment_date, r.expiry_date
        FROM requests r
        JOIN users other_user ON other_user.id = IF(r.sender_id = %s, r.receiver_id, r.sender_id)
        WHERE r.id = %s
          AND %s IN (r.sender_id, r.receiver_id)
          AND COALESCE(other_user.is_deleted, FALSE) = FALSE
          AND COALESCE(other_user.is_blocked, FALSE) = FALSE
        LIMIT 1
        """,
        (user_id, request_id, user_id)
    )
    return cursor.fetchone()


def get_user_chat_subscription(cursor, user_id):
    ensure_premium_schema(cursor)
    expire_chat_access(cursor)
    cursor.execute(
        """
        SELECT id AS user_id,
               premium_unlocked_at AS unlock_date,
               premium_expiry_date AS expiry_date
        FROM users
        WHERE id = %s
          AND COALESCE(is_premium, FALSE) = TRUE
          AND premium_expiry_date > NOW()
        LIMIT 1
        """,
        (user_id,)
    )
    user_subscription = cursor.fetchone()
    if user_subscription:
        return user_subscription

    cursor.execute(
        """
        SELECT p.id,
               p.request_id,
               COALESCE(p.premium_start_date, r.payment_date, p.updated_at, p.created_at) AS unlock_date,
               COALESCE(p.premium_expiry_date, r.expiry_date, DATE_ADD(COALESCE(p.updated_at, p.created_at), INTERVAL 90 DAY)) AS expiry_date
        FROM payments p
        LEFT JOIN requests r
          ON r.id = p.request_id
         AND %s IN (r.sender_id, r.receiver_id)
        WHERE p.user_id = %s
          AND (p.payment_status = 'paid' OR p.status = 'successful')
          AND COALESCE(p.premium_expiry_date, r.expiry_date, DATE_ADD(COALESCE(p.updated_at, p.created_at), INTERVAL 90 DAY)) > NOW()
        ORDER BY COALESCE(p.premium_expiry_date, r.expiry_date, DATE_ADD(COALESCE(p.updated_at, p.created_at), INTERVAL 90 DAY)) DESC
        LIMIT 1
        """,
        (user_id, user_id)
    )
    payment_subscription = cursor.fetchone()
    if payment_subscription:
        cursor.execute(
            """
            UPDATE users
            SET is_premium = TRUE,
                premium_unlocked_at = COALESCE(%s, NOW()),
                premium_expiry_date = %s
            WHERE id = %s
            """,
            (payment_subscription.get('unlock_date'), payment_subscription.get('expiry_date'), user_id)
        )
    return payment_subscription


def has_user_chat_unlock(cursor, user_id, request_id=None):
    return bool(get_user_chat_subscription(cursor, user_id))


def get_chat_access_state(cursor, req, current_user_id):
    if not req or req.get('status') != 'accepted':
        return {
            'is_unlocked': False,
            'current_user_paid': False,
            'other_user_paid': False,
            'lock_message': 'Request must be accepted before chat can open.'
        }

    current_user_id = int(current_user_id)
    sender_id = int(req['sender_id'])
    receiver_id = int(req['receiver_id'])
    current_subscription = get_user_chat_subscription(cursor, current_user_id)
    current_user_paid = bool(current_subscription)
    other_user_id = receiver_id if sender_id == current_user_id else sender_id
    other_user_paid = has_user_chat_unlock(cursor, other_user_id)

    lock_message = get_chat_lock_message(req)

    return {
        'is_unlocked': current_user_paid,
        'current_user_paid': current_user_paid,
        'other_user_paid': other_user_paid,
        'unlock_date': current_subscription.get('unlock_date') if current_subscription else None,
        'expiry_date': current_subscription.get('expiry_date') if current_subscription else None,
        'lock_message': None if current_user_paid else lock_message
    }


def get_chat_lock_message(req=None):
    if req and req.get('payment_status') == 'expired':
        return 'Your chat access has expired. Please unlock again to continue.'
    return 'Unlock premium chat to start messaging.'


def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None

    conn = get_db_connection()
    if not conn:
        return None

    try:
        with conn.cursor() as cursor:
            ensure_user_public_profile_columns(cursor)
            ensure_premium_schema(cursor)
            ensure_engagement_schema(cursor)
            update_daily_activity(cursor, user_id)
            cursor.execute(
                """
                SELECT id, username, full_name, email, skills_offered, skills_wanted,
                       location, avatar_url, bio, video_url, video_description,
                       phone, contact_number, instagram_id, contact_sharing,
                       allow_contact_after_payment, email_notifications, profile_visibility,
                       match_notifications, is_blocked, COALESCE(is_admin, FALSE) AS is_admin,
                       COALESCE(is_deleted, FALSE) AS is_deleted,
                       COALESCE(xp_points, 0) AS xp_points,
                       COALESCE(current_streak, 0) AS current_streak,
                       COALESCE(longest_streak, 0) AS longest_streak,
                       last_reward_claimed_at,
                       COALESCE(is_premium, FALSE) AS is_premium,
                       premium_expiry_date,
                       COALESCE(user_session_version, 1) AS user_session_version
                FROM users WHERE id = %s
                """,
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                current_session_version = session.get('user_session_version')
                row_session_version = int(row.get('user_session_version') or 1)
                if current_session_version is None:
                    session['user_session_version'] = row_session_version
                elif int(current_session_version or 0) != row_session_version:
                    clear_user_session_state()
                    return None
                if row.get('is_blocked') or row.get('is_deleted'):
                    clear_user_session_state()
                    return None
                normalized_avatar = normalize_avatar_url(row.get('avatar_url'), row.get('username'))
                if normalized_avatar and row.get('avatar_url') != normalized_avatar:
                    cursor.execute(
                        "UPDATE users SET avatar_url = %s WHERE id = %s",
                        (normalized_avatar, user_id)
                    )
                    conn.commit()
                row['avatar_url'] = normalized_avatar
                conn.commit()
            return row
    except Exception as e:
        print(f"Error fetching current user: {e}")
        return None
    finally:
        conn.close()


def get_current_admin():
    admin_id = session.get('admin_id')
    admin_logged_in = session.get('admin_logged_in')
    if not admin_logged_in or session.get('admin_session_version') != ADMIN_SESSION_VERSION:
        for key in ADMIN_SESSION_KEYS:
            session.pop(key, None)
        return None
    login_time = session.get('admin_login_time')
    if not login_time:
        for key in ADMIN_SESSION_KEYS:
            session.pop(key, None)
        return None
    try:
        login_datetime = datetime.fromisoformat(login_time)
        if login_datetime.tzinfo is None:
            login_datetime = login_datetime.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - login_datetime > timedelta(hours=ADMIN_SESSION_HOURS):
            for key in ADMIN_SESSION_KEYS:
                session.pop(key, None)
            flash('Session expired. Please login again', 'error')
            return None
    except ValueError:
        for key in ADMIN_SESSION_KEYS:
            session.pop(key, None)
        return None

    if admin_logged_in:
        session.permanent = False
        return {
            'id': admin_id or 0,
            'username': session.get('admin_username', ADMIN_USERNAME),
            'full_name': session.get('admin_name', 'Admin'),
        }

    conn = get_db_connection()
    if not conn:
        return None

    try:
        with conn.cursor() as cursor:
            ensure_unfollow_report_schema(cursor)
            ensure_engagement_schema(cursor)
            cursor.execute(
                "SELECT id, username, full_name, email FROM users WHERE id = %s AND is_admin = TRUE",
                (admin_id,)
            )
            return cursor.fetchone()
    except Exception as e:
        print(f"Error fetching current admin: {e}")
        return None
    finally:
        conn.close()


def admin_required():
    admin = get_current_admin()
    if not admin:
        return None, redirect(url_for('admin_login_page'))
    return admin, None


@app.before_request
def validate_csrf_token():
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return
    if request.endpoint in CSRF_EXEMPT_ENDPOINTS:
        return
    if not is_csrf_valid():
        return csrf_error_response()


@app.before_request
def protect_admin_routes():
    allowed_admin_endpoints = {
        'admin_login_page',
        'admin_forgot_password_page',
        'static',
    }
    if request.path.startswith('/admin') and request.endpoint not in allowed_admin_endpoints:
        admin, response = admin_required()
        if response:
            return response


@app.before_request
def automatic_subscription_reminders():
    if request.endpoint == 'static':
        return
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cursor:
            run_subscription_reminder_job(cursor)
            conn.commit()
    except Exception as e:
        print(f"Error running subscription reminders: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


@app.after_request
def apply_security_headers(response):
    if request.path.startswith('/admin') or (session.get('user_id') and request.endpoint != 'static'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['Vary'] = 'Cookie'
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    if request.endpoint != 'static':
        token = get_csrf_token()
        if token:
            response.set_cookie(
                'sf_csrf_token',
                token,
                httponly=False,
                secure=app.config.get('SESSION_COOKIE_SECURE', False),
                samesite='Lax',
            )
    return response


def ensure_admin_schema(cursor):
    cursor.execute("SHOW COLUMNS FROM users LIKE 'email'")
    email_column = cursor.fetchone()
    if email_column and str(email_column.get('Type', '')).lower() != 'varchar(190)':
        cursor.execute("ALTER TABLE users MODIFY email VARCHAR(190) NOT NULL")
    if not column_exists(cursor, 'users', 'is_blocked'):
        cursor.execute("ALTER TABLE users ADD COLUMN is_blocked BOOLEAN DEFAULT FALSE")
    if not column_exists(cursor, 'users', 'is_deleted'):
        cursor.execute("ALTER TABLE users ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE")
    if not column_exists(cursor, 'users', 'deleted_at'):
        cursor.execute("ALTER TABLE users ADD COLUMN deleted_at TIMESTAMP NULL")
    if not column_exists(cursor, 'users', 'deleted_by_user'):
        cursor.execute("ALTER TABLE users ADD COLUMN deleted_by_user BOOLEAN DEFAULT FALSE")
    if not column_exists(cursor, 'users', 'profile_visibility'):
        cursor.execute("ALTER TABLE users ADD COLUMN profile_visibility BOOLEAN DEFAULT TRUE")
    if not column_exists(cursor, 'users', 'is_verified'):
        cursor.execute("ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT TRUE")
    if not column_exists(cursor, 'users', 'verification_otp'):
        cursor.execute("ALTER TABLE users ADD COLUMN verification_otp VARCHAR(10) DEFAULT NULL")
    if not column_exists(cursor, 'users', 'verification_token'):
        cursor.execute("ALTER TABLE users ADD COLUMN verification_token VARCHAR(120) DEFAULT NULL")
    if not column_exists(cursor, 'users', 'verification_expiry'):
        cursor.execute("ALTER TABLE users ADD COLUMN verification_expiry DATETIME DEFAULT NULL")
    if not column_exists(cursor, 'users', 'verification_last_sent_at'):
        cursor.execute("ALTER TABLE users ADD COLUMN verification_last_sent_at DATETIME DEFAULT NULL")
    ensure_user_unique_indexes(cursor)
    ensure_email_security_schema(cursor)
    ensure_unfollow_report_schema(cursor)
    ensure_engagement_schema(cursor)

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INT(11) NOT NULL AUTO_INCREMENT,
            reported_user_id INT(11) NOT NULL,
            reported_by INT(11) NOT NULL,
            reporter_user_id INT(11) DEFAULT NULL,
            reporter_username VARCHAR(120) DEFAULT NULL,
            reported_username VARCHAR(120) DEFAULT NULL,
            reason ENUM('Spam', 'Abuse', 'Fake', 'Other') NOT NULL,
            description TEXT DEFAULT NULL,
            status ENUM('pending', 'under_review', 'resolved', 'rejected') NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY reported_user_id (reported_user_id),
            KEY reported_by (reported_by),
            CONSTRAINT fk_reports_reported_user FOREIGN KEY (reported_user_id) REFERENCES users(id) ON DELETE CASCADE,
            CONSTRAINT fk_reports_reporter FOREIGN KEY (reported_by) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    if not column_exists(cursor, 'reports', 'reported_user_id'):
        cursor.execute("ALTER TABLE reports ADD COLUMN reported_user_id INT(11) DEFAULT NULL AFTER id")
    if not column_exists(cursor, 'reports', 'reported_by'):
        cursor.execute("ALTER TABLE reports ADD COLUMN reported_by INT(11) DEFAULT NULL AFTER reported_user_id")
    if not column_exists(cursor, 'reports', 'reporter_user_id'):
        cursor.execute("ALTER TABLE reports ADD COLUMN reporter_user_id INT(11) DEFAULT NULL AFTER reported_by")
    if not column_exists(cursor, 'reports', 'reporter_username'):
        cursor.execute("ALTER TABLE reports ADD COLUMN reporter_username VARCHAR(120) DEFAULT NULL AFTER reporter_user_id")
    if not column_exists(cursor, 'reports', 'reported_username'):
        cursor.execute("ALTER TABLE reports ADD COLUMN reported_username VARCHAR(120) DEFAULT NULL AFTER reporter_username")
    if not column_exists(cursor, 'reports', 'reason'):
        cursor.execute("ALTER TABLE reports ADD COLUMN reason ENUM('Spam', 'Abuse', 'Fake', 'Other') NOT NULL DEFAULT 'Other' AFTER reported_username")
    if not column_exists(cursor, 'reports', 'description'):
        cursor.execute("ALTER TABLE reports ADD COLUMN description TEXT DEFAULT NULL AFTER reason")
    if not column_exists(cursor, 'reports', 'status'):
        cursor.execute("ALTER TABLE reports ADD COLUMN status ENUM('pending', 'under_review', 'resolved', 'rejected') NOT NULL DEFAULT 'pending' AFTER description")
    else:
        cursor.execute("ALTER TABLE reports MODIFY status ENUM('Pending', 'Reviewed', 'Resolved', 'pending', 'under_review', 'resolved', 'rejected') DEFAULT 'pending'")
        cursor.execute(
            """
            UPDATE reports
            SET status = CASE
                WHEN status IS NULL OR status = '' THEN 'pending'
                WHEN LOWER(status) = 'pending' THEN 'pending'
                WHEN LOWER(status) = 'reviewed' THEN 'under_review'
                WHEN LOWER(status) = 'under_review' THEN 'under_review'
                WHEN LOWER(status) = 'resolved' THEN 'resolved'
                WHEN LOWER(status) = 'rejected' THEN 'rejected'
                ELSE 'pending'
            END
            """
        )
        cursor.execute("ALTER TABLE reports MODIFY status ENUM('pending', 'under_review', 'resolved', 'rejected') NOT NULL DEFAULT 'pending'")
    if not column_exists(cursor, 'reports', 'created_at'):
        cursor.execute("ALTER TABLE reports ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER status")
    cursor.execute("UPDATE reports SET reporter_user_id = reported_by WHERE reporter_user_id IS NULL AND reported_by IS NOT NULL")
    cursor.execute("UPDATE reports SET reported_by = reporter_user_id WHERE reported_by IS NULL AND reporter_user_id IS NOT NULL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_settings (
            id INT(11) NOT NULL AUTO_INCREMENT,
            setting_key VARCHAR(80) NOT NULL,
            setting_value TEXT DEFAULT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY setting_key (setting_key)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_actions (
            id INT(11) NOT NULL AUTO_INCREMENT,
            user_id INT(11) DEFAULT NULL,
            username VARCHAR(120) DEFAULT NULL,
            action_type VARCHAR(40) NOT NULL,
            admin_name VARCHAR(120) NOT NULL,
            account_status VARCHAR(40) DEFAULT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY user_id (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    if not column_exists(cursor, 'admin_actions', 'username'):
        cursor.execute("ALTER TABLE admin_actions ADD COLUMN username VARCHAR(120) DEFAULT NULL AFTER user_id")
    if not column_exists(cursor, 'admin_actions', 'account_status'):
        cursor.execute("ALTER TABLE admin_actions ADD COLUMN account_status VARCHAR(40) DEFAULT NULL AFTER admin_name")
    if not column_exists(cursor, 'admin_actions', 'action_reason'):
        cursor.execute("ALTER TABLE admin_actions ADD COLUMN action_reason TEXT DEFAULT NULL AFTER account_status")
    if not column_exists(cursor, 'users', 'block_reason'):
        cursor.execute("ALTER TABLE users ADD COLUMN block_reason TEXT DEFAULT NULL")
    if not column_exists(cursor, 'users', 'delete_reason'):
        cursor.execute("ALTER TABLE users ADD COLUMN delete_reason TEXT DEFAULT NULL")
    ensure_admin_activity_schema(cursor)

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_notifications (
            id INT(11) NOT NULL AUTO_INCREMENT,
            notification_type VARCHAR(40) NOT NULL DEFAULT 'system',
            title VARCHAR(190) NOT NULL,
            message TEXT DEFAULT NULL,
            related_id INT(11) DEFAULT NULL,
            icon VARCHAR(80) DEFAULT 'fa-solid fa-bell',
            is_read BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            read_at TIMESTAMP NULL,
            PRIMARY KEY (id),
            KEY notification_type (notification_type),
            KEY is_read (is_read),
            KEY created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    notification_columns = {
        'notification_type': "VARCHAR(40) NOT NULL DEFAULT 'system'",
        'title': "VARCHAR(190) NOT NULL DEFAULT 'Notification'",
        'message': 'TEXT DEFAULT NULL',
        'related_id': 'INT(11) DEFAULT NULL',
        'icon': "VARCHAR(80) DEFAULT 'fa-solid fa-bell'",
        'is_read': 'BOOLEAN NOT NULL DEFAULT FALSE',
        'created_at': 'TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP',
        'read_at': 'TIMESTAMP NULL',
    }
    for column, definition in notification_columns.items():
        if not column_exists(cursor, 'admin_notifications', column):
            cursor.execute(f"ALTER TABLE admin_notifications ADD COLUMN `{column}` {definition}")

    cursor.execute(
        "INSERT IGNORE INTO admin_settings (setting_key, setting_value) VALUES (%s, %s)",
        ('platform_name', 'SkillFlow')
    )
    cursor.execute(
        "INSERT IGNORE INTO admin_settings (setting_key, setting_value) VALUES (%s, %s)",
        ('admin_username', ADMIN_USERNAME)
    )
    cursor.execute("SELECT setting_value FROM admin_settings WHERE setting_key = 'admin_password_hash'")
    if not cursor.fetchone():
        save_admin_setting(cursor, 'admin_password_hash', generate_password_hash(ADMIN_PASSWORD))
    cursor.execute(
        "INSERT IGNORE INTO admin_settings (setting_key, setting_value) VALUES (%s, %s)",
        ('phonepe_client_id', PHONEPE_CLIENT_ID)
    )
    cursor.execute(
        "INSERT IGNORE INTO admin_settings (setting_key, setting_value) VALUES (%s, %s)",
        ('phonepe_client_secret', PHONEPE_CLIENT_SECRET)
    )
    default_settings = {
        'phonepe_merchant_id': '',
        'phonepe_payment_mode': 'test',
        'chat_unlock_price': '99',
        'currency': 'INR',
        'appearance_mode': 'light',
        'email_notifications_enabled': 'on',
        'admin_alerts_enabled': 'on',
        'payment_notifications_enabled': 'on',
    }
    for key, value in default_settings.items():
        cursor.execute(
            "INSERT IGNORE INTO admin_settings (setting_key, setting_value) VALUES (%s, %s)",
            (key, value)
        )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_accounts (
            id INT(11) NOT NULL AUTO_INCREMENT,
            username VARCHAR(120) NOT NULL,
            email VARCHAR(190) NOT NULL,
            password VARCHAR(255) NOT NULL,
            reset_code VARCHAR(10) DEFAULT NULL,
            reset_code_expiry DATETIME DEFAULT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY username (username),
            UNIQUE KEY email (email)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    admin_columns = {
        'username': "VARCHAR(120) NOT NULL DEFAULT 'admin'",
        'email': f"VARCHAR(190) NOT NULL DEFAULT '{ADMIN_EMAIL}'",
        'password': "VARCHAR(255) NOT NULL DEFAULT ''",
        'reset_code': 'VARCHAR(10) DEFAULT NULL',
        'reset_code_expiry': 'DATETIME DEFAULT NULL',
        'created_at': 'TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP',
    }
    for column, definition in admin_columns.items():
        if not column_exists(cursor, 'admin_accounts', column):
            cursor.execute(f"ALTER TABLE admin_accounts ADD COLUMN `{column}` {definition}")

    cursor.execute("SELECT setting_value FROM admin_settings WHERE setting_key = 'admin_password_hash'")
    settings_password = cursor.fetchone()
    initial_admin_password = (
        settings_password['setting_value']
        if settings_password and settings_password.get('setting_value')
        else generate_password_hash(ADMIN_PASSWORD)
    )
    cursor.execute(
        """
        INSERT INTO admin_accounts (username, email, password, created_at)
        VALUES (%s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
            username = VALUES(username),
            email = VALUES(email)
        """,
        (ADMIN_USERNAME, ADMIN_EMAIL, initial_admin_password)
    )
    cursor.execute(
        "UPDATE admin_accounts SET email = %s WHERE username = %s OR LOWER(email) = LOWER(%s)",
        (ADMIN_EMAIL, ADMIN_USERNAME, ADMIN_EMAIL)
    )
    cursor.execute(
        "UPDATE admin_accounts SET password = %s WHERE (password IS NULL OR password = '') AND username = %s",
        (initial_admin_password, ADMIN_USERNAME)
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_plans (
            id INT(11) NOT NULL AUTO_INCREMENT,
            name VARCHAR(50) NOT NULL,
            platform_fee_percent DECIMAL(5,2) NOT NULL DEFAULT 0,
            minimum_transaction_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY plan_name (name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )

    for name, fee, minimum in (('Basic', 5, 100), ('Premium', 8, 250), ('Expert', 10, 500)):
        cursor.execute(
            """
            INSERT IGNORE INTO platform_plans (name, platform_fee_percent, minimum_transaction_amount)
            VALUES (%s, %s, %s)
            """,
            (name, fee, minimum)
        )
    ensure_performance_indexes(cursor)


def table_exists(cursor, table_name):
    cursor.execute("SHOW TABLES LIKE %s", (table_name,))
    return bool(cursor.fetchone())


def column_exists(cursor, table_name, column_name):
    cursor.execute("SHOW COLUMNS FROM `{}` LIKE %s".format(table_name), (column_name,))
    return bool(cursor.fetchone())


def ensure_chat_attachment_schema(cursor):
    if not table_exists(cursor, 'messages'):
        return
    attachment_columns = {
        'attachment_name': 'VARCHAR(255) DEFAULT NULL',
        'attachment_path': 'VARCHAR(255) DEFAULT NULL',
        'attachment_type': 'VARCHAR(120) DEFAULT NULL',
    }
    for column, definition in attachment_columns.items():
        if not column_exists(cursor, 'messages', column):
            cursor.execute(f"ALTER TABLE messages ADD COLUMN `{column}` {definition}")


def index_exists(cursor, table_name, index_name):
    cursor.execute("SHOW INDEX FROM `{}` WHERE Key_name = %s".format(table_name), (index_name,))
    return bool(cursor.fetchone())


def equivalent_index_exists(cursor, table_name, columns):
    cursor.execute("SHOW INDEX FROM `{}`".format(table_name))
    grouped = {}
    for row in cursor.fetchall():
        grouped.setdefault(row.get('Key_name'), []).append(row)
    for rows in grouped.values():
        ordered_columns = [
            row.get('Column_name')
            for row in sorted(rows, key=lambda item: item.get('Seq_in_index') or 0)
        ]
        if ordered_columns[:len(columns)] == columns:
            return True
    return False


def unique_column_index_exists(cursor, table_name, column_name):
    cursor.execute("SHOW INDEX FROM `{}` WHERE Column_name = %s AND Non_unique = 0".format(table_name), (column_name,))
    return bool(cursor.fetchone())


def ensure_user_unique_indexes(cursor):
    # Usernames are validated by the app, but email is the only database-level
    # identity key. This avoids username index conflicts during profile edits.
    cursor.execute("SHOW INDEX FROM users WHERE Key_name = 'username' AND Non_unique = 0")
    if cursor.fetchone():
        cursor.execute("ALTER TABLE users DROP INDEX username")

    if not unique_column_index_exists(cursor, 'users', 'email'):
        cursor.execute(
            """
            SELECT LOWER(email) AS value_key, COUNT(*) AS count
            FROM users
            GROUP BY value_key
            HAVING count > 1
            LIMIT 1
            """
        )
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD UNIQUE KEY email (email)")


PERFORMANCE_INDEXES_CHECKED = False
ENGAGEMENT_SCHEMA_CHECKED = False


def ensure_performance_indexes(cursor):
    global PERFORMANCE_INDEXES_CHECKED
    if PERFORMANCE_INDEXES_CHECKED:
        return
    # Fix: keep user-scoped pages fast and avoid ambiguous full scans during auth/request/chat loads.
    index_specs = {
        'users': {
            'idx_users_email': '(`email`)',
            'idx_users_status': '(`is_deleted`, `is_blocked`, `is_admin`, `profile_visibility`)',
        },
        'requests': {
            'idx_requests_sender_status': '(`sender_id`, `status`, `created_at`)',
            'idx_requests_receiver_status': '(`receiver_id`, `status`, `created_at`)',
            'idx_requests_pair': '(`sender_id`, `receiver_id`)',
        },
        'matches': {
            'idx_matches_user1': '(`user1_id`, `matched_at`)',
            'idx_matches_user2': '(`user2_id`, `matched_at`)',
            'idx_matches_request': '(`request_id`)',
        },
        'payments': {
            'idx_payments_user_status': '(`user_id`, `payment_status`, `status`)',
            'idx_payments_request': '(`request_id`)',
            'idx_payments_merchant_order': '(`merchant_order_id`)',
        },
        'messages': {
            'idx_messages_request_created': '(`request_id`, `created_at`)',
            'idx_messages_sender_receiver': '(`sender_id`, `receiver_id`, `created_at`)',
        },
        'unfollow_reports': {
            'idx_unfollow_reports_request': '(`request_id`)',
            'idx_unfollow_reports_user': '(`unfollower_id`, `unfollowed_user_id`)',
        },
    }
    for table_name, indexes in index_specs.items():
        if not table_exists(cursor, table_name):
            continue
        for index_name, columns_sql in indexes.items():
            columns = re.findall(r'`([^`]+)`', columns_sql)
            if not all(column_exists(cursor, table_name, column) for column in columns):
                continue
            if not index_exists(cursor, table_name, index_name) and not equivalent_index_exists(cursor, table_name, columns):
                cursor.execute(f"ALTER TABLE `{table_name}` ADD INDEX `{index_name}` {columns_sql}")
    PERFORMANCE_INDEXES_CHECKED = True


def ensure_engagement_schema(cursor):
    global ENGAGEMENT_SCHEMA_CHECKED
    if ENGAGEMENT_SCHEMA_CHECKED:
        return
    user_columns = {
        'xp_points': 'INT NOT NULL DEFAULT 0',
        'current_streak': 'INT NOT NULL DEFAULT 0',
        'longest_streak': 'INT NOT NULL DEFAULT 0',
        'last_activity_date': 'DATE DEFAULT NULL',
        'last_reward_claimed_at': 'DATETIME DEFAULT NULL',
    }
    for column, definition in user_columns.items():
        if not column_exists(cursor, 'users', column):
            cursor.execute(f"ALTER TABLE users ADD COLUMN `{column}` {definition}")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_achievements (
            id INT(11) NOT NULL AUTO_INCREMENT,
            user_id INT(11) NOT NULL,
            badge_key VARCHAR(60) NOT NULL,
            badge_name VARCHAR(120) NOT NULL,
            icon VARCHAR(80) DEFAULT 'fa-solid fa-award',
            earned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY user_badge (user_id, badge_key),
            KEY user_id (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_reviews (
            id INT(11) NOT NULL AUTO_INCREMENT,
            reviewer_id INT(11) NOT NULL,
            reviewed_user_id INT(11) NOT NULL,
            request_id INT(11) DEFAULT NULL,
            rating INT NOT NULL,
            feedback VARCHAR(500) DEFAULT NULL,
            experience_tag VARCHAR(120) DEFAULT NULL,
            status ENUM('visible', 'removed') NOT NULL DEFAULT 'visible',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY reviewer_reviewed (reviewer_id, reviewed_user_id),
            KEY reviewed_user_id (reviewed_user_id),
            KEY status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_favorites (
            id INT(11) NOT NULL AUTO_INCREMENT,
            user_id INT(11) NOT NULL,
            favorite_user_id INT(11) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY user_favorite (user_id, favorite_user_id),
            KEY user_id (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_notifications (
            id INT(11) NOT NULL AUTO_INCREMENT,
            user_id INT(11) NOT NULL,
            notification_type VARCHAR(50) NOT NULL DEFAULT 'system',
            title VARCHAR(160) NOT NULL,
            message VARCHAR(500) DEFAULT NULL,
            related_id INT(11) DEFAULT NULL,
            is_read BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY user_unread (user_id, is_read),
            KEY created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_activity (
            id INT(11) NOT NULL AUTO_INCREMENT,
            user_id INT(11) NOT NULL,
            activity_type VARCHAR(60) NOT NULL,
            title VARCHAR(160) NOT NULL,
            points INT NOT NULL DEFAULT 0,
            related_id INT(11) DEFAULT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY user_created (user_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_categories (
            id INT(11) NOT NULL AUTO_INCREMENT,
            category_name VARCHAR(120) NOT NULL,
            icon VARCHAR(80) DEFAULT 'fa-solid fa-layer-group',
            keywords TEXT DEFAULT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY category_name (category_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    if not column_exists(cursor, 'skill_categories', 'icon'):
        cursor.execute("ALTER TABLE skill_categories ADD COLUMN icon VARCHAR(80) DEFAULT 'fa-solid fa-layer-group' AFTER category_name")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_skill_categories (
            id INT(11) NOT NULL AUTO_INCREMENT,
            user_id INT(11) NOT NULL,
            category_id INT(11) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY user_category (user_id, category_id),
            KEY user_id (user_id),
            KEY category_id (category_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    default_categories = {
        'Programming': 'programming,coding,software,algorithm,c,cpp,c++,javascript,typescript',
        'Web Development': 'web development,html,css,javascript,react,node,frontend,backend,full stack',
        'Python': 'python,django,flask,pandas,automation',
        'Java': 'java,spring,android,kotlin',
        'UI/UX Design': 'ui,ux,ui/ux,figma,wireframe,prototype,user experience',
        'Graphic Design': 'graphic design,photoshop,illustrator,canva,branding,logo',
        'Video Editing': 'video editing,premiere,after effects,capcut,reels,youtube editing',
        'Digital Marketing': 'digital marketing,seo,social media,ads,marketing,google ads',
        'Cooking': 'cooking,baking,recipes,chef,food',
        'Photography': 'photography,photo editing,lightroom,camera,portrait',
        'Language Learning': 'english,spanish,french,german,hindi,language,ielts,spoken english',
        'Music': 'music,guitar,piano,singing,vocals,keyboard',
        'Fitness': 'fitness,yoga,gym,workout,nutrition,training',
        'Public Speaking': 'public speaking,presentation,communication,stage,confidence',
        'Content Writing': 'content writing,copywriting,blog,writing,script writing',
        'AI & Machine Learning': 'ai,machine learning,ml,data science,deep learning,chatgpt,prompt',
        'Cloud Computing': 'cloud,aws,azure,gcp,devops,docker,kubernetes',
        'Business': 'business,startup,finance,sales,entrepreneurship,management',
        'Excel & Office Skills': 'excel,office,powerpoint,word,spreadsheet,ms office',
        'Other Skills': 'other,general,custom,misc',
    }
    for category, keywords in default_categories.items():
        cursor.execute(
            """
            INSERT INTO skill_categories (category_name, icon, keywords)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE icon = VALUES(icon), keywords = VALUES(keywords)
            """,
            (category, SKILL_CATEGORY_ICONS.get(category, 'fa-solid fa-layer-group'), keywords)
        )
    ENGAGEMENT_SCHEMA_CHECKED = True


def ensure_user_settings_schema(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            id INT(11) NOT NULL AUTO_INCREMENT,
            user_id INT(11) NOT NULL,
            contact_info_visibility VARCHAR(32) NOT NULL DEFAULT 'matched',
            show_demo_video_publicly BOOLEAN NOT NULL DEFAULT TRUE,
            show_location_publicly BOOLEAN NOT NULL DEFAULT TRUE,
            request_notifications BOOLEAN NOT NULL DEFAULT TRUE,
            chat_notifications BOOLEAN NOT NULL DEFAULT TRUE,
            review_notifications BOOLEAN NOT NULL DEFAULT TRUE,
            payment_notifications BOOLEAN NOT NULL DEFAULT TRUE,
            allow_matched_messages BOOLEAN NOT NULL DEFAULT TRUE,
            auto_scroll_messages BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY user_id (user_id),
            CONSTRAINT user_settings_user_fk
                FOREIGN KEY (user_id) REFERENCES users(id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )


def default_user_settings():
    return {
        'contact_info_visibility': 'matched',
        'show_demo_video_publicly': True,
        'show_location_publicly': True,
        'request_notifications': True,
        'chat_notifications': True,
        'review_notifications': True,
        'payment_notifications': True,
        'allow_matched_messages': True,
        'auto_scroll_messages': True,
    }


def bool_setting(value, default=True):
    if isinstance(value, bool):
        return value
    if value in (1, '1', 'true', 'True', 'on', 'yes'):
        return True
    if value in (0, '0', 'false', 'False', 'off', 'no'):
        return False
    return default


def clean_user_settings_payload(payload):
    settings = default_user_settings()
    visibility = payload.get('contact_info_visibility', settings['contact_info_visibility'])
    if visibility not in {'public', 'matched', 'hidden'}:
        visibility = settings['contact_info_visibility']
    settings['contact_info_visibility'] = visibility
    for key in (
        'show_demo_video_publicly',
        'show_location_publicly',
        'request_notifications',
        'chat_notifications',
        'review_notifications',
        'payment_notifications',
        'allow_matched_messages',
        'auto_scroll_messages',
    ):
        settings[key] = bool_setting(payload.get(key), settings[key])
    return settings


def add_user_xp(cursor, user_id, points, activity_type, title, related_id=None):
    ensure_engagement_schema(cursor)
    points = int(points or 0)
    if points <= 0:
        return
    cursor.execute(
        "UPDATE users SET xp_points = COALESCE(xp_points, 0) + %s WHERE id = %s",
        (points, user_id)
    )
    cursor.execute(
        "INSERT INTO user_activity (user_id, activity_type, title, points, related_id) VALUES (%s, %s, %s, %s, %s)",
        (user_id, activity_type, title, points, related_id)
    )


def create_user_notification(cursor, user_id, notification_type, title, message, related_id=None):
    ensure_engagement_schema(cursor)
    cursor.execute(
        """
        INSERT INTO user_notifications (user_id, notification_type, title, message, related_id)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (user_id, notification_type, title, message, related_id)
    )


def award_achievement(cursor, user_id, badge_key):
    ensure_engagement_schema(cursor)
    badge = ENGAGEMENT_BADGES.get(badge_key)
    if not badge:
        return
    cursor.execute(
        """
        INSERT IGNORE INTO user_achievements (user_id, badge_key, badge_name, icon)
        VALUES (%s, %s, %s, %s)
        """,
        (user_id, badge_key, badge[0], badge[1])
    )


def update_daily_activity(cursor, user_id):
    ensure_engagement_schema(cursor)
    return


def calculate_shared_message_streak(cursor, request_id, user_id, partner_id):
    cursor.execute(
        """
        SELECT DATE(created_at) AS activity_day, COUNT(DISTINCT sender_id) AS speakers
        FROM messages
        WHERE request_id = %s AND sender_id IN (%s, %s)
        GROUP BY DATE(created_at)
        ORDER BY activity_day DESC
        LIMIT 45
        """,
        (request_id, user_id, partner_id)
    )
    rows = cursor.fetchall()
    two_way_days = {row['activity_day'] for row in rows if int(row.get('speakers') or 0) >= 2}
    current = 0
    day = datetime.now().date()
    while day in two_way_days:
        current += 1
        day -= timedelta(days=1)
    best = 0
    running = 0
    for row in sorted(rows, key=lambda item: item['activity_day']):
        if int(row.get('speakers') or 0) >= 2:
            running += 1
            best = max(best, running)
        else:
            running = 0
    return current, best


def get_learning_partner_rows(cursor, user_id, limit=12):
    ensure_engagement_schema(cursor)
    ensure_chat_attachment_schema(cursor)
    ensure_unfollow_report_schema(cursor)
    cursor.execute(
        f"""
        SELECT r.id AS request_id, r.skill_requested, r.skill_offered, r.payment_status, r.created_at AS connected_at,
               other_user.id, other_user.username, other_user.full_name, other_user.avatar_url,
               other_user.skills_offered, other_user.skills_wanted,
               (SELECT MAX(m.created_at) FROM messages m WHERE m.request_id = r.id) AS last_interaction_at,
               (SELECT MAX(m.created_at) FROM messages m WHERE m.request_id = r.id AND m.sender_id = %s) AS last_outgoing_at,
               (SELECT MAX(m.created_at) FROM messages m WHERE m.request_id = r.id AND m.receiver_id = %s) AS last_incoming_at,
               (SELECT COUNT(*) FROM messages m WHERE m.request_id = r.id) AS message_count,
               (SELECT COUNT(*) FROM messages m WHERE m.request_id = r.id AND m.attachment_path IS NOT NULL) AS shared_files
        FROM requests r
        JOIN users other_user ON other_user.id = IF(r.sender_id = %s, r.receiver_id, r.sender_id)
        WHERE r.status = 'accepted'
          AND %s IN (r.sender_id, r.receiver_id)
          AND {active_relationship_filter_sql('r')}
          AND COALESCE(other_user.is_deleted, FALSE) = FALSE
          AND COALESCE(other_user.is_blocked, FALSE) = FALSE
          AND COALESCE(other_user.is_admin, FALSE) = FALSE
        ORDER BY last_interaction_at DESC, r.created_at DESC
        LIMIT %s
        """,
        (user_id, user_id, user_id, user_id, limit)
    )
    partners = []
    now = datetime.now()
    for row in cursor.fetchall():
        current_streak, best_streak = calculate_shared_message_streak(cursor, row['request_id'], user_id, row['id'])
        last_in = row.get('last_incoming_at')
        last_out = row.get('last_outgoing_at')
        last_interaction = row.get('last_interaction_at')
        two_way_recent = isinstance(last_in, datetime) and isinstance(last_out, datetime) and now - min(last_in, last_out) <= timedelta(hours=24)
        if two_way_recent:
            status = 'active'
            status_label = 'Active shared streak'
        elif isinstance(last_interaction, datetime) and now - last_interaction <= timedelta(hours=24):
            status = 'pending'
            status_label = 'Waiting for reply'
        elif isinstance(last_interaction, datetime) and now - last_interaction <= timedelta(hours=72):
            status = 'warning'
            status_label = 'Streak at risk'
        else:
            status = 'broken'
            status_label = 'Needs new interaction'
        row['avatar_url'] = normalize_avatar_url(row.get('avatar_url'), row.get('username'))
        row['current_streak'] = current_streak
        row['longest_streak'] = best_streak
        row['status'] = status
        row['status_label'] = status_label
        row['xp_points'] = int(row.get('message_count') or 0) * 2 + int(row.get('shared_files') or 0) * 5
        partners.append(row)
    return partners


def get_user_badges(cursor, user_id, limit=8):
    ensure_engagement_schema(cursor)
    cursor.execute(
        """
        SELECT badge_key, badge_name, icon, earned_at
        FROM user_achievements
        WHERE user_id = %s
        ORDER BY earned_at DESC
        LIMIT %s
        """,
        (user_id, limit)
    )
    return cursor.fetchall()


def get_skill_category_map(cursor):
    ensure_engagement_schema(cursor)
    cursor.execute("SELECT id, category_name, icon, keywords FROM skill_categories ORDER BY category_name")
    return cursor.fetchall()


def skill_categories_for_text(cursor, text):
    categories = []
    haystack = (text or '').lower()
    if not haystack:
        return categories
    for row in get_skill_category_map(cursor):
        keywords = [item.strip().lower() for item in (row.get('keywords') or '').split(',') if item.strip()]
        if any(keyword and keyword in haystack for keyword in keywords):
            categories.append(row['category_name'])
    return categories[:3]


def get_all_skill_categories(cursor):
    ensure_engagement_schema(cursor)
    cursor.execute(
        """
        SELECT sc.id, sc.category_name, sc.icon, sc.keywords,
               COUNT(DISTINCT usc.user_id) AS saved_users
        FROM skill_categories sc
        LEFT JOIN user_skill_categories usc ON usc.category_id = sc.id
        GROUP BY sc.id, sc.category_name, sc.icon, sc.keywords
        ORDER BY sc.category_name
        """
    )
    return cursor.fetchall()


def get_user_selected_category_ids(cursor, user_id):
    ensure_engagement_schema(cursor)
    cursor.execute("SELECT category_id FROM user_skill_categories WHERE user_id = %s", (user_id,))
    return {int(row.get('category_id')) for row in cursor.fetchall() if row.get('category_id')}


def save_user_skill_categories(cursor, user_id, category_ids):
    ensure_engagement_schema(cursor)
    clean_ids = []
    for category_id in category_ids or []:
        try:
            clean_ids.append(int(category_id))
        except (TypeError, ValueError):
            continue
    clean_ids = list(dict.fromkeys(clean_ids))

    cursor.execute("DELETE FROM user_skill_categories WHERE user_id = %s", (user_id,))
    if not clean_ids:
        return

    cursor.execute(
        "SELECT id FROM skill_categories WHERE id IN ({})".format(','.join(['%s'] * len(clean_ids))),
        clean_ids
    )
    valid_ids = [row['id'] for row in cursor.fetchall()]
    for category_id in valid_ids:
        cursor.execute(
            "INSERT IGNORE INTO user_skill_categories (user_id, category_id) VALUES (%s, %s)",
            (user_id, category_id)
        )


def fetch_category_users(cursor, category_id=None, limit=6):
    ensure_engagement_schema(cursor)
    params = []
    where_parts = [
        "COALESCE(u.is_deleted, FALSE) = FALSE",
        "COALESCE(u.is_blocked, FALSE) = FALSE",
        "COALESCE(u.is_admin, FALSE) = FALSE",
        "COALESCE(u.profile_visibility, TRUE) = TRUE",
    ]
    if category_id:
        cursor.execute("SELECT keywords FROM skill_categories WHERE id = %s", (category_id,))
        category = cursor.fetchone() or {}
        keywords = [item.strip() for item in (category.get('keywords') or '').split(',') if item.strip()]
        related_parts = ["EXISTS (SELECT 1 FROM user_skill_categories usc WHERE usc.user_id = u.id AND usc.category_id = %s)"]
        related_params = [category_id]
        for keyword in keywords[:8]:
            related_parts.append("(u.skills_offered LIKE %s OR u.skills_wanted LIKE %s)")
            related_params.extend([f"%{keyword}%", f"%{keyword}%"])
        where_parts.append(f"({' OR '.join(related_parts)})")
        params.extend(related_params)

    params.append(limit)
    cursor.execute(
        f"""
        SELECT DISTINCT u.id, u.username, u.full_name, u.avatar_url, u.skills_offered, u.skills_wanted
        FROM users u
        WHERE {' AND '.join(where_parts)}
        ORDER BY COALESCE(u.xp_points, 0) DESC, u.id DESC
        LIMIT %s
        """,
        tuple(params)
    )
    users = []
    for row in cursor.fetchall():
        row['avatar_url'] = normalize_avatar_url(row.get('avatar_url'), row.get('username'))
        users.append(row)
    return users


def fetch_skill_users(cursor, skill_name, current_user_id=None, limit=60):
    ensure_engagement_schema(cursor)
    skill_name = (skill_name or '').strip()
    if not skill_name:
        return []

    like_value = f"%{skill_name}%"
    where_params = [like_value, like_value]
    where_parts = [
        "COALESCE(u.is_deleted, FALSE) = FALSE",
        "COALESCE(u.is_blocked, FALSE) = FALSE",
        "COALESCE(u.is_admin, FALSE) = FALSE",
        "COALESCE(u.profile_visibility, TRUE) = TRUE",
        "(u.skills_offered LIKE %s OR u.skills_wanted LIKE %s)",
    ]
    if current_user_id:
        where_parts.append("u.id != %s")
        where_params.append(current_user_id)
    params = [like_value, like_value] + where_params + [limit]
    cursor.execute(
        f"""
        SELECT DISTINCT u.id, u.username, u.full_name, u.avatar_url, u.skills_offered, u.skills_wanted,
               CASE
                   WHEN u.skills_offered LIKE %s THEN 0
                   WHEN u.skills_wanted LIKE %s THEN 1
                   ELSE 2
               END AS skill_match_rank
        FROM users u
        WHERE {' AND '.join(where_parts)}
        ORDER BY skill_match_rank ASC, COALESCE(u.xp_points, 0) DESC, u.id DESC
        LIMIT %s
        """,
        tuple(params)
    )
    users = []
    for row in cursor.fetchall():
        row['avatar_url'] = normalize_avatar_url(row.get('avatar_url'), row.get('username'))
        users.append(row)
    return users


def get_user_engagement_dashboard(cursor, user):
    ensure_engagement_schema(cursor)
    ensure_premium_schema(cursor)
    engagement = {
        'badges': get_user_badges(cursor, user['id']),
        'leaderboard': [],
        'activity': [],
        'daily_users': [],
        'saved_users': [],
        'unread_notifications': 0,
        'unread_messages': 0,
        'can_claim_reward': False,
        'premium_active': bool(get_user_chat_subscription(cursor, user['id'])),
        'categories': skill_categories_for_text(cursor, f"{user.get('skills_offered') or ''},{user.get('skills_wanted') or ''}")
    }
    cursor.execute(
        "SELECT xp_points, current_streak, longest_streak, last_reward_claimed_at, premium_expiry_date FROM users WHERE id = %s",
        (user['id'],)
    )
    fresh_user = cursor.fetchone() or {}
    user.update(fresh_user)
    last_reward = fresh_user.get('last_reward_claimed_at')
    engagement['can_claim_reward'] = datetime.now() - last_reward >= timedelta(hours=24) if isinstance(last_reward, datetime) else not last_reward
    if engagement['premium_active']:
        award_achievement(cursor, user['id'], 'premium_user')
    cursor.execute(
        "SELECT COUNT(*) AS count FROM user_notifications WHERE user_id = %s AND is_read = FALSE",
        (user['id'],)
    )
    engagement['unread_notifications'] = int((cursor.fetchone() or {}).get('count') or 0)
    cursor.execute(
        "SELECT COUNT(*) AS count FROM messages WHERE receiver_id = %s AND COALESCE(is_read, 0) = 0",
        (user['id'],)
    )
    engagement['unread_messages'] = int((cursor.fetchone() or {}).get('count') or 0)
    learning_partners = get_learning_partner_rows(cursor, user['id'], limit=8)
    engagement['leaderboard'] = learning_partners
    engagement['daily_users'] = learning_partners[:3]
    if learning_partners:
        user['current_streak'] = max(int(row.get('current_streak') or 0) for row in learning_partners)
        user['longest_streak'] = max(int(user.get('longest_streak') or 0), max(int(row.get('longest_streak') or 0) for row in learning_partners))
    else:
        user['current_streak'] = 0
        user['longest_streak'] = 0
    cursor.execute(
        """
        SELECT activity_type, title, points, created_at
        FROM user_activity
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (user['id'],)
    )
    engagement['activity'] = cursor.fetchall()
    cursor.execute(
        """
        SELECT u.id, u.username, u.full_name, u.avatar_url
        FROM user_favorites f
        JOIN users u ON u.id = f.favorite_user_id
        WHERE f.user_id = %s
          AND COALESCE(u.is_deleted, FALSE) = FALSE
          AND COALESCE(u.is_blocked, FALSE) = FALSE
        ORDER BY f.created_at DESC
        LIMIT 8
        """,
        (user['id'],)
    )
    engagement['saved_users'] = cursor.fetchall()
    for row in engagement['saved_users']:
        row['avatar_url'] = normalize_avatar_url(row.get('avatar_url'), row.get('username'))
    return engagement


def ensure_email_security_schema(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS disposable_email_attempts (
            id INT(11) NOT NULL AUTO_INCREMENT,
            email VARCHAR(190) NOT NULL,
            domain VARCHAR(120) NOT NULL,
            source VARCHAR(40) NOT NULL DEFAULT 'registration',
            ip_address VARCHAR(80) DEFAULT NULL,
            user_agent VARCHAR(255) DEFAULT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY domain (domain),
            KEY created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )


def ensure_payment_schema(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id INT(11) NOT NULL AUTO_INCREMENT,
            user_id INT(11) NOT NULL,
            request_id INT(11) DEFAULT NULL,
            amount DECIMAL(10,2) NOT NULL,
            status ENUM('created', 'successful', 'failed') NOT NULL DEFAULT 'created',
            gateway VARCHAR(30) NOT NULL DEFAULT 'phonepe',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY user_id (user_id),
            KEY request_id (request_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )

    columns = {
        'gateway': "VARCHAR(30) NOT NULL DEFAULT 'phonepe'",
        'merchant_order_id': 'VARCHAR(120) DEFAULT NULL',
        'transaction_id': 'VARCHAR(120) DEFAULT NULL',
        'payment_status': "VARCHAR(30) NOT NULL DEFAULT 'pending'",
        'premium_start_date': 'TIMESTAMP NULL DEFAULT NULL',
        'premium_expiry_date': 'TIMESTAMP NULL DEFAULT NULL',
        'updated_at': 'TIMESTAMP NULL DEFAULT NULL',
    }
    for column, definition in columns.items():
        if not column_exists(cursor, 'payments', column):
            cursor.execute(f"ALTER TABLE payments ADD COLUMN `{column}` {definition}")


def ensure_premium_schema(cursor):
    ensure_payment_schema(cursor)
    user_columns = {
        'is_premium': 'BOOLEAN DEFAULT FALSE',
        'premium_unlocked_at': 'TIMESTAMP NULL DEFAULT NULL',
        'premium_expiry_date': 'TIMESTAMP NULL DEFAULT NULL',
    }
    for column, definition in user_columns.items():
        if not column_exists(cursor, 'users', column):
            cursor.execute(f"ALTER TABLE users ADD COLUMN `{column}` {definition}")


def ensure_subscription_reminder_schema(cursor):
    ensure_premium_schema(cursor)
    ensure_engagement_schema(cursor)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_settings (
            id INT(11) NOT NULL AUTO_INCREMENT,
            setting_key VARCHAR(80) NOT NULL,
            setting_value TEXT DEFAULT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY setting_key (setting_key)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_reminder_logs (
            id INT(11) NOT NULL AUTO_INCREMENT,
            user_id INT(11) NOT NULL,
            reminder_key VARCHAR(60) NOT NULL,
            expiry_date DATE NOT NULL,
            notification_id INT(11) DEFAULT NULL,
            sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY user_reminder_expiry (user_id, reminder_key, expiry_date),
            KEY user_id (user_id),
            KEY sent_at (sent_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    defaults = {
        'subscription_reminders_enabled': 'on',
        'subscription_reminder_7': 'on',
        'subscription_reminder_3': 'on',
        'subscription_reminder_1': 'on',
        'subscription_reminder_expired': 'on',
        'subscription_reminder_last_run': '',
    }
    for key, value in defaults.items():
        cursor.execute(
            "INSERT IGNORE INTO admin_settings (setting_key, setting_value) VALUES (%s, %s)",
            (key, value)
        )


def get_subscription_reminder_settings(cursor):
    ensure_subscription_reminder_schema(cursor)
    cursor.execute(
        """
        SELECT setting_key, setting_value
        FROM admin_settings
        WHERE setting_key IN (
            'subscription_reminders_enabled',
            'subscription_reminder_7',
            'subscription_reminder_3',
            'subscription_reminder_1',
            'subscription_reminder_expired',
            'subscription_reminder_last_run'
        )
        """
    )
    settings = {row['setting_key']: row['setting_value'] for row in cursor.fetchall()}
    return {
        'enabled': settings.get('subscription_reminders_enabled', 'on') == 'on',
        'before_7': settings.get('subscription_reminder_7', 'on') == 'on',
        'before_3': settings.get('subscription_reminder_3', 'on') == 'on',
        'before_1': settings.get('subscription_reminder_1', 'on') == 'on',
        'expired': settings.get('subscription_reminder_expired', 'on') == 'on',
        'last_run': settings.get('subscription_reminder_last_run', ''),
    }


def subscription_remaining_days(expiry):
    if not expiry:
        return None
    if isinstance(expiry, datetime):
        expiry_date = expiry.date()
    else:
        expiry_date = expiry
    return (expiry_date - datetime.now().date()).days


def send_subscription_reminder(cursor, user_row, reminder_key=None, force=False):
    ensure_subscription_reminder_schema(cursor)
    expiry = user_row.get('premium_expiry_date')
    if not expiry:
        return False
    remaining = subscription_remaining_days(expiry)
    expiry_date = expiry.date() if isinstance(expiry, datetime) else expiry
    if reminder_key is None:
        if remaining is None:
            return False
        if remaining <= 0:
            reminder_key = 'expired'
        elif remaining in (7, 3, 1):
            reminder_key = f'before_{remaining}'
        else:
            return False
    if not force:
        cursor.execute(
            "SELECT id FROM subscription_reminder_logs WHERE user_id = %s AND reminder_key = %s AND expiry_date = %s LIMIT 1",
            (user_row['id'], reminder_key, expiry_date)
        )
        if cursor.fetchone():
            return False
    if reminder_key == 'expired' or (remaining is not None and remaining <= 0):
        title = 'Your subscription has expired.'
        message = f'Your premium subscription expired on {expiry_date}. Renew now to continue premium access.'
    else:
        days = remaining if remaining is not None else reminder_key.replace('before_', '')
        title = f'Your premium subscription expires in {days} day{"s" if str(days) != "1" else ""}.'
        message = f'Renew now to continue premium access. Expiry date: {expiry_date}.'
    create_user_notification(cursor, user_row['id'], 'premium', title, message)
    notification_id = cursor.lastrowid
    log_key = reminder_key if not force else f'manual_{datetime.now().strftime("%Y%m%d%H%M%S")}'
    cursor.execute(
        """
        INSERT INTO subscription_reminder_logs (user_id, reminder_key, expiry_date, notification_id)
        VALUES (%s, %s, %s, %s)
        """,
        (user_row['id'], log_key, expiry_date, notification_id)
    )
    return True


def run_subscription_reminder_job(cursor, force=False):
    settings = get_subscription_reminder_settings(cursor)
    if not settings['enabled'] and not force:
        return 0
    if not force and settings.get('last_run'):
        try:
            last_run = datetime.fromisoformat(settings['last_run'])
            if datetime.now() - last_run < timedelta(hours=6):
                return 0
        except ValueError:
            pass
    cursor.execute(
        """
        SELECT id, username, full_name, premium_expiry_date
        FROM users
        WHERE COALESCE(is_admin, FALSE) = FALSE
          AND premium_expiry_date IS NOT NULL
          AND premium_expiry_date <= DATE_ADD(NOW(), INTERVAL 7 DAY)
        """
    )
    sent = 0
    for user_row in cursor.fetchall():
        remaining = subscription_remaining_days(user_row.get('premium_expiry_date'))
        key = None
        if remaining is not None and remaining <= 0 and settings['expired']:
            key = 'expired'
        elif remaining == 1 and settings['before_1']:
            key = 'before_1'
        elif remaining == 3 and settings['before_3']:
            key = 'before_3'
        elif remaining == 7 and settings['before_7']:
            key = 'before_7'
        if key and send_subscription_reminder(cursor, user_row, key):
            sent += 1
    cursor.execute(
        """
        INSERT INTO admin_settings (setting_key, setting_value, updated_at)
        VALUES ('subscription_reminder_last_run', %s, NOW())
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value), updated_at = NOW()
        """,
        (datetime.now().isoformat(timespec='seconds'),)
    )
    return sent


def ensure_unfollow_report_schema(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS unfollow_reports (
            id INT(11) NOT NULL AUTO_INCREMENT,
            match_id INT(11) DEFAULT NULL,
            request_id INT(11) DEFAULT NULL,
            unfollower_id INT(11) NOT NULL,
            unfollowed_user_id INT(11) NOT NULL,
            action_type VARCHAR(40) NOT NULL DEFAULT 'unfollow',
            previous_request_status VARCHAR(40) DEFAULT NULL,
            reason VARCHAR(80) NOT NULL,
            custom_reason TEXT DEFAULT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY match_id (match_id),
            KEY request_id (request_id),
            KEY unfollower_id (unfollower_id),
            KEY unfollowed_user_id (unfollowed_user_id),
            KEY status (status),
            KEY reason (reason)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """
    )
    columns = {
        'match_id': 'INT(11) DEFAULT NULL',
        'request_id': 'INT(11) DEFAULT NULL',
        'unfollower_id': 'INT(11) NOT NULL',
        'unfollowed_user_id': 'INT(11) NOT NULL',
        'action_type': "VARCHAR(40) NOT NULL DEFAULT 'unfollow'",
        'previous_request_status': 'VARCHAR(40) DEFAULT NULL',
        'reason': 'VARCHAR(80) NOT NULL',
        'custom_reason': 'TEXT DEFAULT NULL',
        'status': "VARCHAR(40) NOT NULL DEFAULT 'pending'",
        'created_at': 'TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP',
    }
    for column, definition in columns.items():
        if not column_exists(cursor, 'unfollow_reports', column):
            cursor.execute(f"ALTER TABLE unfollow_reports ADD COLUMN `{column}` {definition}")


def insert_unfollow_report_safely(cursor, report_data):
    try:
        try:
            ensure_unfollow_report_schema(cursor)
        except Exception as schema_error:
            print(f"Unfollow report schema warning: {type(schema_error).__name__}: {schema_error}")

        if not table_exists(cursor, 'unfollow_reports'):
            return False

        cursor.execute("SHOW COLUMNS FROM unfollow_reports")
        columns = {row.get('Field') for row in cursor.fetchall()}
        if 'request_id' not in columns:
            try:
                cursor.execute("ALTER TABLE unfollow_reports ADD COLUMN `request_id` INT(11) DEFAULT NULL")
                columns.add('request_id')
            except Exception as alter_error:
                print(f"Unfollow report request_id warning: {type(alter_error).__name__}: {alter_error}")
                return False

        request_id = report_data.get('request_id')
        if request_id and 'request_id' in columns:
            cursor.execute("SELECT id FROM unfollow_reports WHERE request_id = %s LIMIT 1", (request_id,))
            if cursor.fetchone():
                return True

        values = {
            'match_id': report_data.get('match_id'),
            'request_id': request_id,
            'unfollower_id': report_data.get('unfollower_id'),
            'unfollowed_user_id': report_data.get('unfollowed_user_id'),
            'action_type': report_data.get('action_type') or 'unfollow',
            'previous_request_status': report_data.get('previous_request_status'),
            'reason': report_data.get('reason') or 'Unfollowed from chat',
            'custom_reason': report_data.get('custom_reason'),
            'status': report_data.get('status') or 'pending',
            'created_at': datetime.now(),
        }
        insert_columns = [column for column in values if column in columns]
        if not insert_columns:
            return False

        placeholders = ', '.join(['%s'] * len(insert_columns))
        column_sql = ', '.join(f'`{column}`' for column in insert_columns)
        cursor.execute(
            f"INSERT INTO unfollow_reports ({column_sql}) VALUES ({placeholders})",
            tuple(values[column] for column in insert_columns)
        )
        return True
    except Exception as report_error:
        print(f"Unfollow report logging skipped: {type(report_error).__name__}: {report_error}")
        return False


def active_relationship_filter_sql(alias='r'):
    return f"""
        NOT EXISTS (
            SELECT 1
            FROM unfollow_reports ur
            WHERE ur.request_id = {alias}.id
        )
    """


def get_relationship_state(cursor, current_user_id, other_user_id):
    ensure_unfollow_report_schema(cursor)
    cursor.execute(
        f"""
        SELECT m.id AS match_id, m.request_id, r.status
        FROM matches m
        LEFT JOIN requests r ON r.id = m.request_id
        WHERE %s IN (m.user1_id, m.user2_id)
          AND %s IN (m.user1_id, m.user2_id)
          AND NOT EXISTS (
              SELECT 1
              FROM unfollow_reports ur
              WHERE ur.request_id = m.request_id
          )
        ORDER BY m.matched_at DESC
        LIMIT 1
        """,
        (current_user_id, other_user_id)
    )
    match = cursor.fetchone()
    if match:
        is_unlocked = bool(match.get('request_id') and has_user_chat_unlock(cursor, current_user_id, match.get('request_id')))
        return {
            'status': 'unlocked' if is_unlocked else 'matched',
            'label': 'Unlocked' if is_unlocked else 'Matched',
            'can_request': False,
            'request_id': match.get('request_id'),
            'match_id': match.get('match_id'),
        }

    cursor.execute(
        f"""
        SELECT id, sender_id, receiver_id, status, created_at
        FROM requests r
        WHERE (
            (sender_id = %s AND receiver_id = %s)
            OR (sender_id = %s AND receiver_id = %s)
        )
          AND {active_relationship_filter_sql('r')}
        ORDER BY
            CASE status
                WHEN 'accepted' THEN 1
                WHEN 'pending' THEN 2
                WHEN 'rejected' THEN 3
                ELSE 4
            END,
            created_at DESC,
            id DESC
        LIMIT 1
        """,
        (current_user_id, other_user_id, other_user_id, current_user_id)
    )
    request_row = cursor.fetchone()
    if not request_row:
        return {
            'status': 'none',
            'label': 'Send Request',
            'can_request': True,
            'request_id': None,
            'match_id': None,
        }

    status = (request_row.get('status') or 'pending').lower()
    is_unlocked = status == 'accepted' and has_user_chat_unlock(cursor, current_user_id, request_row.get('id'))
    labels = {
        'pending': 'Request Sent' if int(request_row.get('sender_id')) == int(current_user_id) else 'Request Pending',
        'accepted': 'Unlocked' if is_unlocked else 'Request Accepted',
        'rejected': 'Rejected',
    }
    return {
        'status': 'unlocked' if is_unlocked else status,
        'label': labels.get(status, status.title()),
        'can_request': False,
        'request_id': request_row.get('id'),
        'match_id': None,
    }


def recommendation_score(current_user, other_user):
    return skill_match_percentage(current_user, other_user)


def fetch_recommended_users(cursor, current_user, offset=0, limit=4):
    ensure_unfollow_report_schema(cursor)
    ensure_engagement_schema(cursor)
    cursor.execute(
        """
        SELECT id, username, full_name, bio, avatar_url, skills_offered, skills_wanted
        FROM users
        WHERE id != %s
          AND COALESCE(is_deleted, FALSE) = FALSE
          AND COALESCE(is_blocked, FALSE) = FALSE
          AND COALESCE(is_admin, FALSE) = FALSE
          AND COALESCE(profile_visibility, TRUE) = TRUE
        """,
        (current_user['id'],)
    )
    users = cursor.fetchall()
    users.sort(
        key=lambda item: (
            -recommendation_score(current_user, item),
            (item.get('full_name') or item.get('username') or '').lower()
        )
    )
    total = len(users)
    selected = users[offset:offset + limit]
    for recommended_user in selected:
        recommended_user['avatar_url'] = normalize_avatar_url(
            recommended_user.get('avatar_url'),
            recommended_user.get('username')
        )
        recommended_user['relationship'] = get_relationship_state(
            cursor,
            current_user['id'],
            recommended_user['id']
        )
        recommended_user.update(enrich_skill_match(current_user, recommended_user))
        recommended_user['categories'] = skill_categories_for_text(
            cursor,
            f"{recommended_user.get('skills_offered') or ''},{recommended_user.get('skills_wanted') or ''}"
        )
    return selected, total


def save_phonepe_payment(cursor, user_id, request_id, amount_rupees, merchant_order_id, transaction_id=None, status='created', payment_status='pending'):
    ensure_payment_schema(cursor)
    cursor.execute(
        "SELECT id, user_id, request_id FROM payments WHERE merchant_order_id = %s ORDER BY id DESC LIMIT 1",
        (merchant_order_id,)
    )
    existing = cursor.fetchone()
    if existing:
        # Fix: never let a payment reference move between users or chat requests.
        if int(existing['user_id']) != int(user_id) or int(existing['request_id'] or 0) != int(request_id or 0):
            raise ValueError('Payment reference does not belong to this user/request')
        cursor.execute(
            """
            UPDATE payments
            SET user_id = %s,
                request_id = %s,
                amount = %s,
                status = %s,
                gateway = 'phonepe',
                transaction_id = %s,
                payment_status = %s,
                merchant_order_id = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                user_id, request_id, amount_rupees, status, transaction_id, payment_status,
                merchant_order_id, existing['id']
            )
        )
        return existing['id']

    cursor.execute(
        """
        INSERT INTO payments (
            user_id, request_id, amount, status, gateway, merchant_order_id,
            transaction_id, payment_status, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, 'phonepe', %s, %s, %s, NOW(), NOW())
        """,
        (
            user_id, request_id, amount_rupees, status, merchant_order_id,
            transaction_id, payment_status
        )
    )
    return cursor.lastrowid


USER_PUBLIC_SCHEMA_CHECKED = False
USER_COLUMN_CACHE = None


def get_user_columns(cursor):
    global USER_COLUMN_CACHE
    if USER_COLUMN_CACHE is None:
        cursor.execute("SHOW COLUMNS FROM users")
        USER_COLUMN_CACHE = {row['Field'] for row in cursor.fetchall()}
    return USER_COLUMN_CACHE


def ensure_user_public_profile_columns(cursor):
    global USER_PUBLIC_SCHEMA_CHECKED, USER_COLUMN_CACHE
    if USER_PUBLIC_SCHEMA_CHECKED:
        ensure_performance_indexes(cursor)
        return
    cursor.execute("SHOW COLUMNS FROM users LIKE 'email'")
    email_column = cursor.fetchone()
    if email_column and str(email_column.get('Type', '')).lower() != 'varchar(190)':
        cursor.execute("ALTER TABLE users MODIFY email VARCHAR(190) NOT NULL")
    columns = {
        'bio': 'TEXT DEFAULT NULL',
        'location': 'VARCHAR(120) DEFAULT NULL',
        'video_url': 'VARCHAR(255) DEFAULT NULL',
        'video_description': 'TEXT DEFAULT NULL',
        'phone': 'VARCHAR(20) DEFAULT NULL',
        'contact_number': 'VARCHAR(30) DEFAULT NULL',
        'instagram_id': 'VARCHAR(120) DEFAULT NULL',
        'contact_sharing': 'BOOLEAN DEFAULT FALSE',
        'allow_contact_after_payment': 'BOOLEAN DEFAULT FALSE',
        'email_notifications': 'BOOLEAN DEFAULT TRUE',
        'profile_visibility': 'BOOLEAN DEFAULT TRUE',
        'match_notifications': 'BOOLEAN DEFAULT TRUE',
        'user_session_version': 'INT DEFAULT 1',
        'is_blocked': 'BOOLEAN DEFAULT FALSE',
        'is_deleted': 'BOOLEAN DEFAULT FALSE',
        'deleted_at': 'TIMESTAMP NULL',
        'deleted_by_user': 'BOOLEAN DEFAULT FALSE',
        'reset_code': 'VARCHAR(10) DEFAULT NULL',
        'reset_code_expiry': 'DATETIME DEFAULT NULL',
        'is_verified': 'BOOLEAN DEFAULT TRUE',
        'verification_otp': 'VARCHAR(10) DEFAULT NULL',
        'verification_token': 'VARCHAR(120) DEFAULT NULL',
        'verification_expiry': 'DATETIME DEFAULT NULL',
        'verification_last_sent_at': 'DATETIME DEFAULT NULL',
    }
    for column, definition in columns.items():
        if not column_exists(cursor, 'users', column):
            cursor.execute(f"ALTER TABLE users ADD COLUMN `{column}` {definition}")
    ensure_user_unique_indexes(cursor)
    ensure_performance_indexes(cursor)
    USER_COLUMN_CACHE = None
    USER_PUBLIC_SCHEMA_CHECKED = True


def has_paid_profile_access(cursor, viewer_id, profile_user_id):
    ensure_unfollow_report_schema(cursor)
    ensure_payment_schema(cursor)
    expire_chat_access(cursor)
    if has_user_chat_unlock(cursor, viewer_id):
        cursor.execute(
            """
            SELECT r.id
            FROM requests r
            WHERE r.status = 'accepted'
              AND (
                (r.sender_id = %s AND r.receiver_id = %s)
                OR (r.sender_id = %s AND r.receiver_id = %s)
              )
              AND NOT EXISTS (
                SELECT 1
                FROM unfollow_reports ur
                WHERE ur.request_id = r.id
              )
            LIMIT 1
            """,
            (viewer_id, profile_user_id, profile_user_id, viewer_id)
        )
        if cursor.fetchone():
            return True

    cursor.execute(
        """
        SELECT r.id
        FROM requests r
        JOIN payments p ON p.request_id = r.id
        WHERE r.status = 'accepted'
          AND p.user_id = %s
          AND (p.payment_status = 'paid' OR p.status = 'successful')
          AND (
            (r.sender_id = %s AND r.receiver_id = %s)
            OR (r.sender_id = %s AND r.receiver_id = %s)
          )
          AND NOT EXISTS (
            SELECT 1
            FROM unfollow_reports ur
            WHERE ur.request_id = r.id
          )
        LIMIT 1
        """,
        (viewer_id, viewer_id, profile_user_id, profile_user_id, viewer_id)
    )
    return bool(cursor.fetchone())


def otp_expiry_timestamp(expiry_value):
    if isinstance(expiry_value, datetime):
        return int(expiry_value.timestamp() * 1000)
    return None

@app.route('/')
def landing_page():
    return render_template('user/index.html')

@app.route('/auth')
def auth_page():
    return render_template('user/sign.html', auth_mode=request.args.get('mode', 'login'))


@app.route('/api/username/check')
def username_check():
    username = normalize_username(request.args.get('username', ''))
    current_user = get_current_user() if request.args.get('current') == '1' else None
    validation_error = username_validation_error(username)
    if validation_error:
        return jsonify({'available': False, 'error': validation_error})

    conn = get_db_connection()
    if not conn:
        return jsonify({'available': False, 'error': 'Database error'}), 500

    try:
        with conn.cursor() as cursor:
            available = is_username_available(cursor, username, current_user['id'] if current_user else None)
            return jsonify({
                'available': available,
                'username': username,
                'error': None if available else 'Username already taken.'
            })
    except Exception as e:
        print(f"Error checking username: {e}")
        return jsonify({'available': False, 'error': 'Unable to check username'}), 500
    finally:
        conn.close()


@app.route('/verify-email', methods=['GET', 'POST'])
def verify_email_page():
    pending_email = normalize_email(request.form.get('email') or request.args.get('email') or session.get('pending_verification_email', ''))
    pending_user_id = session.get('pending_verification_user_id')
    otp_expires_at = None
    cooldown_remaining = 0

    if not pending_email:
        flash('Please sign up or login to verify your email.', 'error')
        return redirect(url_for('auth_page'))

    conn = get_db_connection()
    if not conn:
        flash('Database connection failed.', 'error')
        return redirect(url_for('auth_page'))

    try:
        with conn.cursor() as cursor:
            ensure_user_public_profile_columns(cursor)
            ensure_email_security_schema(cursor)
            cursor.execute(
                """
                SELECT id, username, email, COALESCE(is_verified, FALSE) AS is_verified,
                       verification_otp, verification_expiry, verification_last_sent_at,
                       COALESCE(is_blocked, FALSE) AS is_blocked,
                       COALESCE(is_deleted, FALSE) AS is_deleted
                FROM users
                WHERE LOWER(email) = LOWER(%s)
                  AND (%s IS NULL OR id = %s)
                ORDER BY id DESC
                LIMIT 1
                """,
                (pending_email, pending_user_id, pending_user_id)
            )
            user = cursor.fetchone()
            if not user:
                flash('Email not found! Please register.', 'error')
                return redirect(url_for('auth_page'))
            if user.get('is_deleted'):
                flash('This account has been deleted. Please contact support.', 'error')
                return redirect(url_for('auth_page'))
            if user.get('is_blocked'):
                flash('Your account is blocked. Please contact support.', 'error')
                return redirect(url_for('auth_page'))
            if user.get('is_verified'):
                session.pop('pending_verification_email', None)
                session.pop('pending_verification_user_id', None)
                flash('Email already verified. Please sign in.', 'success')
                return redirect(url_for('auth_page'))

            cooldown_seconds = get_verification_cooldown_seconds(cursor)
            _, cooldown_remaining = can_send_verification_email(user, cooldown_seconds)

            if request.method == 'POST':
                otp = request.form.get('verification_otp', '').strip()
                if not otp:
                    flash('Verification OTP is required.', 'error')
                else:
                    cursor.execute(
                        """
                        SELECT id, username
                        FROM users
                        WHERE LOWER(email) = LOWER(%s)
                          AND id = %s
                          AND verification_otp = %s
                          AND verification_expiry IS NOT NULL
                          AND verification_expiry >= NOW()
                        LIMIT 1
                        """,
                        (pending_email, user['id'], otp)
                    )
                    verified_user = cursor.fetchone()
                    if not verified_user:
                        flash('Invalid or expired verification OTP.', 'error')
                    else:
                        cursor.execute(
                            """
                            UPDATE users
                            SET is_verified = TRUE,
                                verification_otp = NULL,
                                verification_token = NULL,
                                verification_expiry = NULL
                            WHERE id = %s
                            """,
                            (verified_user['id'],)
                        )
                        conn.commit()
                        start_user_session(verified_user)
                        flash('Email verified successfully. Welcome to SkillFlow.', 'success')
                        return redirect(url_for('dashboard_page'))

            otp_expires_at = verification_expiry_timestamp(user.get('verification_expiry'))
            return render_template(
                'user/verify_email.html',
                verification_email=pending_email,
                otp_expires_at=otp_expires_at,
                cooldown_remaining=cooldown_remaining
            )
    except Exception as e:
        print(f"Error verifying email: {e}")
        traceback.print_exc()
        flash('Unable to verify email right now.', 'error')
        return redirect(url_for('auth_page'))
    finally:
        conn.close()


@app.route('/resend-verification', methods=['POST'])
def resend_verification_email():
    pending_email = normalize_email(request.form.get('email') or session.get('pending_verification_email', ''))
    pending_user_id = session.get('pending_verification_user_id')
    if not pending_email:
        flash('Please enter your email before requesting verification.', 'error')
        return redirect(url_for('auth_page'))

    conn = get_db_connection()
    if not conn:
        flash('Database connection failed.', 'error')
        return redirect(url_for('verify_email_page', email=pending_email))

    try:
        with conn.cursor() as cursor:
            ensure_user_public_profile_columns(cursor)
            ensure_email_security_schema(cursor)
            cursor.execute(
                """
                SELECT id, email, COALESCE(is_verified, FALSE) AS is_verified,
                       verification_last_sent_at
                FROM users
                WHERE LOWER(email) = LOWER(%s)
                  AND (%s IS NULL OR id = %s)
                ORDER BY id DESC
                LIMIT 1
                """,
                (pending_email, pending_user_id, pending_user_id)
            )
            user = cursor.fetchone()
            if not user:
                flash('Email not found! Please register.', 'error')
                return redirect(url_for('auth_page'))
            if user.get('is_verified'):
                flash('Email already verified. Please sign in.', 'success')
                return redirect(url_for('auth_page'))

            cooldown_seconds = get_verification_cooldown_seconds(cursor)
            allowed, remaining = can_send_verification_email(user, cooldown_seconds)
            if not allowed:
                flash(f'Please wait {remaining} seconds before requesting another verification email.', 'error')
                return redirect(url_for('verify_email_page', email=pending_email))

            otp, _ = issue_verification_otp(cursor, user['id'], user['email'])
            conn.commit()
            session['pending_verification_email'] = user['email']
            session['pending_verification_user_id'] = user['id']
            if send_verification_email(user['email'], otp):
                flash('Verification email sent.', 'success')
            else:
                flash('Verification email could not be sent. Please try again later.', 'error')
    except Exception as e:
        print(f"Error resending verification email: {e}")
        traceback.print_exc()
        flash('Unable to resend verification email.', 'error')
    finally:
        conn.close()
    return redirect(url_for('verify_email_page', email=pending_email))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password_page():
    reset_email = ''
    show_otp_form = False
    show_password_form = False
    otp_expires_at = None

    if request.method == 'POST':
        action = request.form.get('action', 'send_otp')
        email = request.form.get('email', '').strip().lower()

        if not email:
            flash('Registered email is required.', 'error')
            return redirect(url_for('forgot_password_page'))

        conn = get_db_connection()
        if not conn:
            flash('Database connection failed.', 'error')
            return redirect(url_for('forgot_password_page'))

        try:
            with conn.cursor() as cursor:
                ensure_user_public_profile_columns(cursor)
                cursor.execute(
                    """
                    SELECT id, email, reset_code, reset_code_expiry,
                           COALESCE(is_blocked, FALSE) AS is_blocked,
                           COALESCE(is_deleted, FALSE) AS is_deleted
                    FROM users
                    WHERE LOWER(email) = LOWER(%s)
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (email,)
                )
                user = cursor.fetchone()
                if not user:
                    flash('Email not found! Please register.', 'error')
                    return redirect(url_for('forgot_password_page'))
                if user.get('is_deleted'):
                    flash('This account has been deleted. Please contact support.', 'error')
                    return redirect(url_for('forgot_password_page'))
                if user.get('is_blocked'):
                    flash('Your account is blocked. Please contact support.', 'error')
                    return redirect(url_for('forgot_password_page'))

                if action == 'send_otp':
                    reset_code = generate_admin_reset_code()
                    reset_code_expiry = datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
                    cursor.execute(
                        """
                        UPDATE users
                        SET reset_code = %s, reset_code_expiry = %s
                        WHERE id = %s
                        """,
                        (reset_code, reset_code_expiry, user['id'])
                    )
                    conn.commit()

                    if send_user_reset_email(user['email'], reset_code):
                        flash('OTP sent to your registered email.', 'success')
                        return render_template(
                            'user/forgot_password.html',
                            reset_email=user['email'],
                            show_otp_form=True,
                            show_password_form=False,
                            otp_expires_at=otp_expiry_timestamp(reset_code_expiry)
                        )

                    cursor.execute(
                        "UPDATE users SET reset_code = NULL, reset_code_expiry = NULL WHERE id = %s",
                        (user['id'],)
                    )
                    conn.commit()
                    flash('Email could not be sent. Please try again later or contact support.', 'error')
                    return render_template(
                        'user/forgot_password.html',
                        reset_email=user['email'],
                        show_otp_form=False,
                        show_password_form=False
                    )

                if action == 'verify_otp':
                    reset_code = request.form.get('reset_code', '').strip()
                    if not reset_code:
                        flash('OTP is required.', 'error')
                        return render_template(
                            'user/forgot_password.html',
                            reset_email=email,
                            show_otp_form=True,
                            show_password_form=False,
                            otp_expires_at=otp_expiry_timestamp(user.get('reset_code_expiry'))
                        )

                    cursor.execute(
                        """
                        SELECT id, email
                        FROM users
                        WHERE id = %s
                          AND LOWER(email) = LOWER(%s)
                          AND reset_code = %s
                          AND reset_code_expiry IS NOT NULL
                          AND reset_code_expiry >= NOW()
                        LIMIT 1
                        """,
                        (user['id'], email, reset_code)
                    )
                    verified_user = cursor.fetchone()
                    if not verified_user:
                        flash('Invalid or expired OTP.', 'error')
                        return render_template(
                            'user/forgot_password.html',
                            reset_email=email,
                            show_otp_form=True,
                            show_password_form=False,
                            otp_expires_at=otp_expiry_timestamp(user.get('reset_code_expiry'))
                        )

                    session['password_reset_user_id'] = verified_user['id']
                    session['password_reset_email'] = verified_user['email']
                    flash('OTP verified. Create a new password.', 'success')
                    return render_template(
                        'user/forgot_password.html',
                        reset_email=verified_user['email'],
                        show_otp_form=False,
                        show_password_form=True
                    )

                if action != 'reset_password':
                    flash('Invalid reset action.', 'error')
                    return redirect(url_for('forgot_password_page'))

                reset_user_id = session.get('password_reset_user_id')
                reset_email = session.get('password_reset_email')
                if reset_user_id != user['id'] or reset_email != user['email']:
                    flash('Please verify OTP before resetting password.', 'error')
                    return render_template(
                        'user/forgot_password.html',
                        reset_email=email,
                        show_otp_form=True,
                        show_password_form=False,
                        otp_expires_at=otp_expiry_timestamp(user.get('reset_code_expiry'))
                    )

                cursor.execute(
                    """
                    SELECT id
                    FROM users
                    WHERE id = %s
                      AND email = %s
                      AND reset_code IS NOT NULL
                      AND reset_code_expiry IS NOT NULL
                      AND reset_code_expiry >= NOW()
                    LIMIT 1
                    """,
                    (user['id'], user['email'])
                )
                if not cursor.fetchone():
                    session.pop('password_reset_user_id', None)
                    session.pop('password_reset_email', None)
                    flash('OTP expired. Please request a new OTP.', 'error')
                    return render_template('user/forgot_password.html', reset_email=email, show_otp_form=False, show_password_form=False)

                new_password = request.form.get('new_password', '')
                confirm_password = request.form.get('confirm_password', '')
                if not new_password or not confirm_password:
                    flash('New password and confirm password are required.', 'error')
                    return render_template('user/forgot_password.html', reset_email=email, show_otp_form=False, show_password_form=True)
                if new_password != confirm_password:
                    flash('Passwords do not match.', 'error')
                    return render_template('user/forgot_password.html', reset_email=email, show_otp_form=False, show_password_form=True)
                if len(new_password) < 8:
                    flash('Password must be at least 8 characters.', 'error')
                    return render_template('user/forgot_password.html', reset_email=email, show_otp_form=False, show_password_form=True)

                cursor.execute(
                    """
                    UPDATE users
                    SET password_hash = %s,
                        reset_code = NULL,
                        reset_code_expiry = NULL
                    WHERE id = %s
                    """,
                    (generate_password_hash(new_password), user['id'])
                )
                conn.commit()
                session.pop('password_reset_user_id', None)
                session.pop('password_reset_email', None)
            flash('Password reset successfully. Please sign in.', 'success')
            return redirect(url_for('auth_page'))
        except Exception as e:
            print(f"Error resetting user password: {e}")
            flash('Unable to reset password.', 'error')
        finally:
            conn.close()

    return render_template(
        'user/forgot_password.html',
        reset_email=reset_email,
        show_otp_form=show_otp_form,
        show_password_form=show_password_form,
        otp_expires_at=otp_expires_at
    )

@app.route('/register', methods=['POST'])
def register():
    if is_rate_limited('register', limit=6, window_seconds=600):
        flash('Too many signup attempts. Please try again later.', 'error')
        return redirect(url_for('auth_page', mode='signup'))
    clear_user_session_state()
    clear_pending_verification_state()
    full_name = (request.form.get('full_name') or request.form.get('fullname') or '').strip()
    requested_username = normalize_username(request.form.get('username', ''))
    email = normalize_email(request.form.get('email', ''))
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')
    location = request.form.get('location', '').strip()
    if not full_name or not email or not password or not confirm_password or not location:
        flash('All fields are required!', 'error')
        return redirect(url_for('auth_page', mode='signup'))

    email_error = email_validation_error(email)
    if email_error:
        flash(email_error, 'error')
        return redirect(url_for('auth_page', mode='signup'))

    if password != confirm_password:
        flash('Passwords do not match!', 'error')
        return redirect(url_for('auth_page', mode='signup'))

    if len(password) < 8:
        flash('Password must be at least 8 characters.', 'error')
        return redirect(url_for('auth_page', mode='signup'))

    skills_offered = ""
    skills_wanted = ""

    conn = get_db_connection()
    if not conn:
        flash('Database connection failed.', 'error')
        return redirect(url_for('auth_page'))

    try:
        with conn.cursor() as cursor:
            ensure_user_public_profile_columns(cursor)
            ensure_email_security_schema(cursor)
            if is_disposable_email(email):
                log_disposable_email_attempt(cursor, email, 'registration')
                conn.commit()
                flash('Temporary or fake email addresses are not allowed.', 'error')
                return redirect(url_for('auth_page', mode='signup'))

            # Check only the submitted email, never stale OTP/session data.
            cursor.execute(
                """
                SELECT *
                FROM users
                WHERE LOWER(TRIM(email)) = %s
                LIMIT 1
                """,
                (email,)
            )
            existing_email_user = cursor.fetchone()
            if existing_email_user and normalize_email(existing_email_user.get('email')) == email:
                if existing_email_user.get('is_deleted'):
                    flash('This email belongs to a deleted account. Please contact the admin to restore it.', 'error')
                elif not existing_email_user.get('is_verified'):
                    session['pending_verification_email'] = existing_email_user['email']
                    session['pending_verification_user_id'] = existing_email_user['id']
                    flash('Account already exists but is not verified. Please verify your email or resend the OTP.', 'error')
                    return redirect(url_for('verify_email_page', email=existing_email_user['email']))
                else:
                    flash('Email is already registered!', 'error')
                return redirect(url_for('auth_page', mode='signup'))
            existing_email_user = None

            if requested_username:
                validation_error = username_validation_error(requested_username)
                if validation_error:
                    flash(validation_error, 'error')
                    return redirect(url_for('auth_page', mode='signup'))
                if not is_username_available(cursor, requested_username):
                    flash('Username already taken.', 'error')
                    return redirect(url_for('auth_page', mode='signup'))
                username = requested_username
            else:
                username = generate_unique_username(cursor, full_name)

            # Hash password and insert
            hashed_pw = generate_password_hash(password)
            default_avatar = avatar_url_for_seed(username)
            cursor.execute(
                """
                INSERT INTO users
                    (username, full_name, email, password_hash, location, skills_offered, skills_wanted,
                     avatar_url, is_verified, verification_token)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s)
                """,
                (
                    username, full_name, email, hashed_pw, location, skills_offered,
                    skills_wanted, default_avatar, secrets.token_urlsafe(32)
                )
            )
            new_user_id = cursor.lastrowid
            verification_otp, verification_expiry = issue_verification_otp(cursor, new_user_id, email)
            create_admin_notification(
                cursor,
                'user',
                'New user registration',
                f'{full_name or username} registered with {email}.',
                related_id=new_user_id,
                icon='fa-solid fa-user-plus'
            )
            conn.commit()
            session['pending_verification_email'] = email
            session['pending_verification_user_id'] = new_user_id
            if send_verification_email(email, verification_otp):
                flash('Registration successful. Please verify your email before continuing.', 'success')
            else:
                flash('Account created, but verification email could not be sent. Use Resend Verification Email.', 'error')
            return redirect(url_for('verify_email_page', email=email))
    except pymysql.err.IntegrityError as e:
        error_text = ' '.join(str(part) for part in getattr(e, 'args', ()) or [e])
        print(f"Registration integrity error: {error_text}")
        if 'email' in error_text.lower():
            flash('Email is already registered!', 'error')
        elif 'username' in error_text.lower():
            flash('Username already taken.', 'error')
        else:
            flash('Unable to create account because of a duplicate value.', 'error')
    except Exception as e:
        print(f"Registration failed: {type(e).__name__}: {e}")
        flash('Unable to create account right now. Please try again.', 'error')
    finally:
        conn.close()

    return redirect(url_for('auth_page', mode='signup'))

@app.route('/login', methods=['POST'])
def login():
    if is_rate_limited('user_login', limit=10, window_seconds=300):
        flash('Too many login attempts. Please try again later.', 'error')
        return redirect(url_for('auth_page'))
    clear_user_session_state()
    email = normalize_email(request.form.get('email', ''))
    password = request.form.get('password', '')
    remember_me = request.form.get('remember_me') == 'on'

    if not email or not password:
        flash('Email and password are required!', 'error')
        return redirect(url_for('auth_page'))
    email_error = email_validation_error(email)
    if email_error:
        flash(email_error, 'error')
        return redirect(url_for('auth_page'))

    conn = get_db_connection()
    if not conn:
        flash('Database connection failed.', 'error')
        return redirect(url_for('auth_page'))

    try:
        with conn.cursor() as cursor:
            ensure_user_public_profile_columns(cursor)
            if column_exists(cursor, 'users', 'is_blocked'):
                cursor.execute(
                    """
                    SELECT id, username, email, password_hash, is_blocked,
                           COALESCE(is_deleted, FALSE) AS is_deleted,
                           COALESCE(is_verified, TRUE) AS is_verified,
                           COALESCE(user_session_version, 1) AS user_session_version
                    FROM users
                    WHERE LOWER(email) = LOWER(%s)
                    ORDER BY id DESC
                    LIMIT 20
                    """,
                    (email,)
                )
            else:
                cursor.execute(
                    """
                    SELECT id, username, email, password_hash, FALSE AS is_blocked,
                           FALSE AS is_deleted, TRUE AS is_verified,
                           1 AS user_session_version
                    FROM users
                    WHERE LOWER(email) = LOWER(%s)
                    ORDER BY id DESC
                    LIMIT 20
                    """,
                    (email,)
                )
            matching_users = cursor.fetchall()
            user = next(
                (candidate for candidate in matching_users if check_password_hash(candidate['password_hash'], password)),
                None
            )

            if not matching_users:
                flash('Email not found! Please register.', 'error')
            elif not user:
                flash('Incorrect password! Please try again.', 'error')
            elif user.get('is_deleted'):
                flash('This account has been deleted. Please contact support.', 'error')
            elif user.get('is_blocked'):
                flash('Your account is blocked. Please contact support.', 'error')
            elif not user.get('is_verified'):
                session['pending_verification_email'] = user['email']
                session['pending_verification_user_id'] = user['id']
                flash('Please verify your email before continuing.', 'error')
                return redirect(url_for('verify_email_page', email=user['email']))
            else:
                start_user_session(user, remember=remember_me)
                return redirect(url_for('dashboard_page'))
    except Exception as e:
        print(f"Login failed: {type(e).__name__}: {e}")
        flash('Unable to sign in right now. Please try again.', 'error')
    finally:
        conn.close()

    return redirect(url_for('auth_page'))

@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    username = session.get('username')
    if user_id:
        conn = get_db_connection()
        if conn:
            try:
                with conn.cursor() as cursor:
                    ensure_admin_schema(cursor)
                    if not username:
                        cursor.execute("SELECT username FROM users WHERE id = %s", (user_id,))
                        row = cursor.fetchone()
                        username = row['username'] if row else None
                    log_admin_action(cursor, 'System', user_id, 'logout', username, 'Logged out')
                    conn.commit()
            except Exception as e:
                print(f"Error logging logout event: {e}")
            finally:
                conn.close()
    clear_user_session_state()
    flash('You have been logged out.', 'success')
    return redirect(url_for('landing_page'))


@app.route('/dashboard')
def dashboard_page():
    user = get_current_user()
    if not user:
        flash('Please log in to access the dashboard.', 'error')
        return redirect(url_for('auth_page'))
    
    conn = get_db_connection()
    recommended_users = []
    stats = {'sent': 0, 'received': 0, 'pending': 0, 'accepted': 0, 'rejected': 0}
    engagement = {
        'badges': [],
        'leaderboard': [],
        'activity': [],
        'daily_users': [],
        'saved_users': [],
        'unread_notifications': 0,
        'unread_messages': 0,
        'can_claim_reward': False,
        'premium_active': False,
        'categories': []
    }
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_engagement_schema(cursor)
                ensure_premium_schema(cursor)
                update_daily_activity(cursor, user['id'])
                recommended_users, _ = fetch_recommended_users(cursor, user, offset=0, limit=4)

                # Fix: one scoped stats query avoids repeated scans and stale session lookups.
                cursor.execute(
                    """
                    SELECT
                        SUM(CASE WHEN sender_id = %s THEN 1 ELSE 0 END) AS sent,
                        SUM(CASE WHEN receiver_id = %s THEN 1 ELSE 0 END) AS received,
                        SUM(CASE WHEN receiver_id = %s AND status = 'pending' THEN 1 ELSE 0 END) AS pending,
                        SUM(CASE WHEN receiver_id = %s AND status = 'accepted' THEN 1 ELSE 0 END) AS accepted,
                        SUM(CASE WHEN receiver_id = %s AND status = 'rejected' THEN 1 ELSE 0 END) AS rejected
                    FROM requests
                    WHERE sender_id = %s OR receiver_id = %s
                    """,
                    (user['id'], user['id'], user['id'], user['id'], user['id'], user['id'], user['id'])
                )
                stats_row = cursor.fetchone() or {}
                stats = {key: int(stats_row.get(key) or 0) for key in stats}
                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM user_notifications
                    WHERE user_id = %s AND is_read = FALSE
                    """,
                    (user['id'],)
                )
                engagement['unread_notifications'] = int((cursor.fetchone() or {}).get('count') or 0)
                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM messages
                    WHERE receiver_id = %s AND COALESCE(is_read, 0) = 0
                    """,
                    (user['id'],)
                )
                engagement['unread_messages'] = int((cursor.fetchone() or {}).get('count') or 0)
                cursor.execute(
                    """
                    SELECT xp_points, current_streak, longest_streak, last_reward_claimed_at,
                           COALESCE(is_premium, FALSE) AS is_premium, premium_expiry_date
                    FROM users
                    WHERE id = %s
                    """,
                    (user['id'],)
                )
                fresh_user = cursor.fetchone() or {}
                user.update(fresh_user)
                last_reward = fresh_user.get('last_reward_claimed_at')
                if isinstance(last_reward, datetime):
                    engagement['can_claim_reward'] = datetime.now() - last_reward >= timedelta(hours=24)
                else:
                    engagement['can_claim_reward'] = not last_reward
                engagement['premium_active'] = bool(get_user_chat_subscription(cursor, user['id']))
                if engagement['premium_active']:
                    award_achievement(cursor, user['id'], 'premium_user')
                engagement['badges'] = get_user_badges(cursor, user['id'])
                cursor.execute(
                    """
                    SELECT id, username, full_name, avatar_url, COALESCE(xp_points, 0) AS xp_points,
                           COALESCE(current_streak, 0) AS current_streak
                    FROM users
                    WHERE COALESCE(is_deleted, FALSE) = FALSE
                      AND COALESCE(is_blocked, FALSE) = FALSE
                      AND COALESCE(is_admin, FALSE) = FALSE
                    ORDER BY COALESCE(xp_points, 0) DESC, COALESCE(current_streak, 0) DESC
                    LIMIT 5
                    """
                )
                engagement['leaderboard'] = cursor.fetchall()
                for row in engagement['leaderboard']:
                    row['avatar_url'] = normalize_avatar_url(row.get('avatar_url'), row.get('username'))
                cursor.execute(
                    """
                    SELECT activity_type, title, points, created_at
                    FROM user_activity
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT 5
                    """,
                    (user['id'],)
                )
                engagement['activity'] = cursor.fetchall()
                engagement['daily_users'] = recommended_users[:2]
                cursor.execute(
                    """
                    SELECT u.id, u.username, u.full_name, u.avatar_url
                    FROM user_favorites f
                    JOIN users u ON u.id = f.favorite_user_id
                    WHERE f.user_id = %s
                      AND COALESCE(u.is_deleted, FALSE) = FALSE
                      AND COALESCE(u.is_blocked, FALSE) = FALSE
                    ORDER BY f.created_at DESC
                    LIMIT 4
                    """,
                    (user['id'],)
                )
                engagement['saved_users'] = cursor.fetchall()
                for row in engagement['saved_users']:
                    row['avatar_url'] = normalize_avatar_url(row.get('avatar_url'), row.get('username'))
                engagement['categories'] = skill_categories_for_text(
                    cursor,
                    f"{user.get('skills_offered') or ''},{user.get('skills_wanted') or ''}"
                )
                conn.commit()

        except Exception as e:
            print(f"Error fetching dashboard data: {e}")
        finally:
            conn.close()

    return render_template('user/dashboard.html', username=user['username'], user=user, recommended_users=recommended_users, stats=stats, engagement=engagement, active_page='dashboard')


@app.route('/notifications')
def notifications_page():
    user = get_current_user()
    if not user:
        flash('Please log in to view notifications.', 'error')
        return redirect(url_for('auth_page'))

    notifications = []
    unread_messages = 0
    unread_alerts = 0
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_engagement_schema(cursor)
                cursor.execute(
                    """
                    SELECT id, notification_type, title, message, related_id, is_read, created_at
                    FROM user_notifications
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    """,
                    (user['id'],)
                )
                notifications = [dict(item) for item in cursor.fetchall()]
                for item in notifications:
                    if item.get('notification_type') == 'premium':
                        item['icon'] = 'fa-solid fa-crown'
                        item['open_url'] = url_for('requests_page')
                        item['action_label'] = 'Renew Now'
                unread_alerts = sum(1 for item in notifications if not item.get('is_read'))
                cursor.execute(
                    "SELECT COUNT(*) AS count FROM messages WHERE receiver_id = %s AND COALESCE(is_read, 0) = 0",
                    (user['id'],)
                )
                unread_messages = int((cursor.fetchone() or {}).get('count') or 0)
                cursor.execute(
                    """
                    SELECT m.id, m.request_id, m.sender_id, COALESCE(m.message_text, m.content) AS message_text,
                           m.created_at, u.username, u.full_name, u.avatar_url
                    FROM messages m
                    JOIN users u ON u.id = m.sender_id
                    WHERE m.receiver_id = %s
                      AND COALESCE(m.is_read, 0) = 0
                    ORDER BY m.created_at DESC
                    """,
                    (user['id'],)
                )
                message_groups = {}
                for row in cursor.fetchall():
                    sender_id = row.get('sender_id')
                    if not sender_id:
                        continue

                    sender_name = row.get('full_name') or row.get('username') or 'Someone'
                    group = message_groups.get(sender_id)
                    if not group:
                        message_groups[sender_id] = {
                            'id': f"message-user-{sender_id}",
                            'notification_type': 'message_summary',
                            'title': sender_name,
                            'message': row.get('message_text') or 'New message',
                            'related_id': row.get('request_id'),
                            'sender_id': sender_id,
                            'sender_name': sender_name,
                            'sender_username': row.get('username'),
                            'avatar_url': normalize_avatar_url(row.get('avatar_url'), row.get('username')),
                            'unread_count': 1,
                            'is_read': False,
                            'created_at': row.get('created_at'),
                            'icon': 'fa-regular fa-message',
                            'open_url': url_for('chat_page', request_id=row.get('request_id'), user_id=sender_id),
                        }
                    else:
                        group['unread_count'] += 1

                notifications.extend(message_groups.values())
                notifications.sort(key=lambda item: item.get('created_at') or datetime.min, reverse=True)
        except Exception as e:
            print(f"Error loading user notifications: {e}")
        finally:
            conn.close()
    return render_template(
        'user/notifications.html',
        user=user,
        notifications=notifications,
        unread_alerts=unread_alerts,
        unread_messages=unread_messages,
        active_page='notifications'
    )


@app.route('/notifications/mark-read', methods=['POST'])
def notifications_mark_read():
    user = get_current_user()
    if not user:
        return redirect(url_for('auth_page'))
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_engagement_schema(cursor)
                cursor.execute("UPDATE user_notifications SET is_read = TRUE WHERE user_id = %s", (user['id'],))
                cursor.execute("UPDATE messages SET is_read = 1 WHERE receiver_id = %s AND COALESCE(is_read, 0) = 0", (user['id'],))
                conn.commit()
        finally:
            conn.close()
    return redirect(url_for('notifications_page'))


@app.route('/reviews')
def reviews_page():
    user = get_current_user()
    if not user:
        flash('Please log in to view reviews.', 'error')
        return redirect(url_for('auth_page'))

    received_reviews = []
    given_reviews = []
    reviewable_users = []
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_engagement_schema(cursor)
                ensure_unfollow_report_schema(cursor)
                cursor.execute(
                    """
                    SELECT rv.rating, rv.feedback, rv.experience_tag, rv.created_at,
                           u.username, u.full_name, u.avatar_url
                    FROM user_reviews rv
                    JOIN users u ON u.id = rv.reviewer_id
                    WHERE rv.reviewed_user_id = %s AND rv.status = 'visible'
                    ORDER BY rv.created_at DESC
                    LIMIT 30
                    """,
                    (user['id'],)
                )
                received_reviews = cursor.fetchall()
                for row in received_reviews:
                    row['avatar_url'] = normalize_avatar_url(row.get('avatar_url'), row.get('username'))
                cursor.execute(
                    """
                    SELECT rv.rating, rv.feedback, rv.experience_tag, rv.created_at,
                           u.username, u.full_name, u.avatar_url
                    FROM user_reviews rv
                    JOIN users u ON u.id = rv.reviewed_user_id
                    WHERE rv.reviewer_id = %s
                    ORDER BY rv.created_at DESC
                    LIMIT 30
                    """,
                    (user['id'],)
                )
                given_reviews = cursor.fetchall()
                for row in given_reviews:
                    row['avatar_url'] = normalize_avatar_url(row.get('avatar_url'), row.get('username'))
                cursor.execute(
                    f"""
                    SELECT DISTINCT other_user.id, other_user.username, other_user.full_name
                    FROM requests r
                    JOIN users other_user ON other_user.id = IF(r.sender_id = %s, r.receiver_id, r.sender_id)
                    WHERE r.status = 'accepted'
                      AND %s IN (r.sender_id, r.receiver_id)
                      AND {active_relationship_filter_sql('r')}
                      AND COALESCE(other_user.is_deleted, FALSE) = FALSE
                      AND COALESCE(other_user.is_blocked, FALSE) = FALSE
                    ORDER BY other_user.username ASC
                    """,
                    (user['id'], user['id'])
                )
                reviewable_users = cursor.fetchall()
        except Exception as e:
            print(f"Error loading reviews page: {e}")
        finally:
            conn.close()
    return render_template('user/reviews.html', user=user, received_reviews=received_reviews, given_reviews=given_reviews, reviewable_users=reviewable_users, active_page='reviews')


@app.route('/daily-activity')
def daily_activity_page():
    user = get_current_user()
    if not user:
        flash('Please log in to view daily activity.', 'error')
        return redirect(url_for('auth_page'))

    engagement = {
        'badges': [],
        'leaderboard': [],
        'activity': [],
        'daily_users': [],
        'saved_users': [],
        'can_claim_reward': False,
        'premium_active': False,
        'categories': []
    }
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                engagement = get_user_engagement_dashboard(cursor, user)
                conn.commit()
        except Exception as e:
            print(f"Error loading daily activity: {e}")
        finally:
            conn.close()
    return render_template('user/daily_activity.html', user=user, engagement=engagement, active_page='daily_activity')


@app.route('/settings', methods=['GET', 'POST'])
def settings_page():
    return redirect(url_for('dashboard_page'))


@app.route('/skill-categories')
def skill_categories_page():
    user = get_current_user()
    if not user:
        flash('Please log in to explore skill categories.', 'error')
        return redirect(url_for('auth_page'))

    categories = []
    selected_category = None
    related_users = []
    selected_id = request.args.get('category_id')
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                categories = get_all_skill_categories(cursor)
                for category in categories:
                    keywords = [item.strip() for item in (category.get('keywords') or '').split(',') if item.strip()]
                    category['preview'] = ' / '.join(keywords[:3]) if keywords else 'Explore related skills'
                if selected_id:
                    try:
                        selected_id = int(selected_id)
                    except (TypeError, ValueError):
                        selected_id = None
                if selected_id:
                    selected_category = next((item for item in categories if int(item.get('id')) == selected_id), None)
                    related_users = fetch_category_users(cursor, selected_id, limit=8)
        except Exception as e:
            print(f"Error loading skill categories: {e}")
        finally:
            conn.close()

    return render_template(
        'user/skill_categories.html',
        user=user,
        categories=categories,
        selected_category=selected_category,
        related_users=related_users,
        active_page='skill_categories'
    )


@app.route('/skill-users/<path:skill_name>')
def skill_users_page(skill_name):
    user = get_current_user()
    if not user:
        flash('Please log in to explore skill users.', 'error')
        return redirect(url_for('auth_page'))

    skill_name = (skill_name or '').strip()
    skill_users = []
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                skill_users = fetch_skill_users(cursor, skill_name, current_user_id=user['id'])
                for skill_user in skill_users:
                    skill_user['relationship'] = get_relationship_state(cursor, user['id'], skill_user['id'])
        except Exception as e:
            print(f"Error loading skill users for {skill_name}: {e}")
        finally:
            conn.close()

    return render_template(
        'user/skill_users.html',
        user=user,
        skill_name=skill_name,
        skill_users=skill_users,
        active_page='skill_categories'
    )


@app.route('/recommendations')
def recommendations_page():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        offset = max(0, int(request.args.get('offset', 0)))
        limit = min(12, max(1, int(request.args.get('limit', 4))))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid pagination'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        with conn.cursor() as cursor:
            users, total = fetch_recommended_users(cursor, user, offset=offset, limit=limit)
        next_offset = offset + len(users)
        return jsonify({
            'users': users,
            'next_offset': next_offset,
            'has_more': next_offset < total
        })
    except Exception as e:
        print(f"Error loading recommendations: {e}")
        return jsonify({'error': 'Unable to load recommendations'}), 500
    finally:
        conn.close()

@app.route('/update_skills', methods=['POST'])
def update_skills():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    skills_offered = (request.form.get('skills_offered') or payload.get('skills_offered') or '').strip()
    skills_wanted = (request.form.get('skills_wanted') or payload.get('skills_wanted') or '').strip()
    if len(skills_offered) > 600 or len(skills_wanted) > 600:
        return jsonify({'error': 'Skills text must be 600 characters or less'}), 400
    
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET skills_offered = %s, skills_wanted = %s WHERE id = %s",
                    (skills_offered, skills_wanted, user['id'])
                )
                conn.commit()
                if request.is_json:
                    return jsonify({'success': True, 'skills_offered': skills_offered, 'skills_wanted': skills_wanted})
                flash('Skills updated successfully!', 'success')
        except Exception as e:
            print(f"Error updating skills: {type(e).__name__}: {e}")
            if request.is_json:
                return jsonify({'error': 'Unable to update skills'}), 500
            flash('Unable to update skills.', 'error')
        finally:
            conn.close()
            
    if request.is_json:
        return jsonify({'error': 'Database connection failed'}), 500
    return redirect(url_for('dashboard_page'))

@app.route('/requests')
def requests_page():
    user = get_current_user()
    if not user:
        flash('Please log in to access requests.', 'error')
        return redirect(url_for('auth_page'))

    return render_template('user/requests.html', username=user['username'], user=user, active_page='requests')

@app.route('/chat')
def chat_page():
    user = get_current_user()
    if not user:
        flash('Please log in to access chat.', 'error')
        return redirect(url_for('auth_page'))

    return render_template(
        'user/chat.html',
        username=user['username'],
        user=user,
        selected_request_id=request.args.get('request_id') or '',
        selected_user_id=request.args.get('user_id') or '',
        active_page='chat'
    )

@app.route('/search')
def search_page():
    user = get_current_user()
    if not user:
        flash('Please log in to access search.', 'error')
        return redirect(url_for('auth_page'))

    return render_template('user/search.html', username=user['username'], user=user, active_page='search')

@app.route('/profile')
def profile_page():
    user = get_current_user()
    if not user:
        flash('Please log in to access profile.', 'error')
        return redirect(url_for('auth_page'))

    avatar_presets = get_avatar_options()
    default_avatar = get_default_avatar_url()
    badges = []
    skill_categories = []
    selected_skill_category_ids = set()
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_engagement_schema(cursor)
                badges = get_user_badges(cursor, user['id'])
                skill_categories = get_all_skill_categories(cursor)
                selected_skill_category_ids = get_user_selected_category_ids(cursor, user['id'])
        finally:
            conn.close()
    return render_template(
        'user/profile.html',
        username=user['username'],
        user=user,
        active_page='profile',
        avatar_presets=avatar_presets,
        default_avatar=default_avatar,
        badges=badges,
        skill_categories=skill_categories,
        selected_skill_category_ids=selected_skill_category_ids,
    )

@app.route('/profile/<int:user_id>')
@app.route('/profile/view/<int:user_id>')
def public_profile_page(user_id):
    user = get_current_user()
    if not user:
        flash('Please log in to view profiles.', 'error')
        return redirect(url_for('auth_page'))

    if user_id == user['id']:
        return redirect(url_for('profile_page'))

    conn = get_db_connection()
    if not conn:
        flash('Database error', 'error')
        return redirect(url_for('requests_page'))

    try:
        with conn.cursor() as cursor:
            ensure_user_public_profile_columns(cursor)
            ensure_engagement_schema(cursor)
            cursor.execute(
                """
                SELECT id, username, full_name, email, location, avatar_url, bio,
                       skills_offered, skills_wanted, video_url, video_description,
                       phone, contact_number, instagram_id, contact_sharing,
                       allow_contact_after_payment
                FROM users
                WHERE id = %s
                  AND COALESCE(is_deleted, FALSE) = FALSE
                  AND COALESCE(is_blocked, FALSE) = FALSE
                  AND COALESCE(profile_visibility, TRUE) = TRUE
                """,
                (user_id,)
            )
            profile_user = cursor.fetchone()
            if not profile_user:
                flash('Profile not found.', 'error')
                return redirect(url_for('requests_page'))

            profile_user['avatar_url'] = normalize_avatar_url(
                profile_user.get('avatar_url'),
                profile_user.get('username')
            )
            contact_allowed = bool(
                profile_user.get('contact_sharing')
                or profile_user.get('allow_contact_after_payment')
            )
            has_paid_access = has_paid_profile_access(cursor, user['id'], user_id)
            profile_user['can_view_contact'] = contact_allowed and has_paid_access
            profile_user['display_contact_number'] = (
                profile_user.get('contact_number') or profile_user.get('phone')
            )
            profile_user['badges'] = get_user_badges(cursor, user_id, limit=6)
            profile_user['categories'] = skill_categories_for_text(
                cursor,
                f"{profile_user.get('skills_offered') or ''},{profile_user.get('skills_wanted') or ''}"
            )
            profile_user['premium_active'] = bool(get_user_chat_subscription(cursor, user_id))
            cursor.execute(
                """
                SELECT AVG(rating) AS avg_rating, COUNT(*) AS review_count
                FROM user_reviews
                WHERE reviewed_user_id = %s AND status = 'visible'
                """,
                (user_id,)
            )
            rating_row = cursor.fetchone() or {}
            profile_user['avg_rating'] = round(float(rating_row.get('avg_rating') or 0), 1)
            profile_user['review_count'] = int(rating_row.get('review_count') or 0)
            cursor.execute(
                """
                SELECT id, rating, feedback, experience_tag
                FROM user_reviews
                WHERE reviewer_id = %s AND reviewed_user_id = %s
                LIMIT 1
                """,
                (user['id'], user_id)
            )
            profile_user['my_review'] = cursor.fetchone()
            cursor.execute(
                "SELECT id FROM user_favorites WHERE user_id = %s AND favorite_user_id = %s LIMIT 1",
                (user['id'], user_id)
            )
            profile_user['is_favorite'] = bool(cursor.fetchone())
            cursor.execute(
                f"""
                SELECT r.id
                FROM requests r
                WHERE r.status = 'accepted'
                  AND (
                    (r.sender_id = %s AND r.receiver_id = %s)
                    OR (r.sender_id = %s AND r.receiver_id = %s)
                  )
                  AND {active_relationship_filter_sql('r')}
                ORDER BY r.created_at DESC
                LIMIT 1
                """,
                (user['id'], user_id, user_id, user['id'])
            )
            review_request = cursor.fetchone()
            profile_user['can_review'] = bool(review_request)
            profile_user['review_request_id'] = review_request.get('id') if review_request else None
            conn.commit()
    except Exception as e:
        print(f"Error loading public profile: {e}")
        flash('Unable to load profile.', 'error')
        return redirect(url_for('requests_page'))
    finally:
        conn.close()

    return render_template(
        'user/profile_view.html',
        username=user['username'],
        user=user,
        profile_user=profile_user,
        active_page='requests'
    )


@app.route('/api/reward/claim', methods=['POST'])
def claim_daily_reward():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_engagement_schema(cursor)
            cursor.execute(
                "SELECT last_reward_claimed_at FROM users WHERE id = %s FOR UPDATE",
                (user['id'],)
            )
            row = cursor.fetchone() or {}
            last_claim = row.get('last_reward_claimed_at')
            if isinstance(last_claim, datetime) and datetime.now() - last_claim < timedelta(hours=24):
                return jsonify({'error': 'Daily reward already claimed'}), 400
            cursor.execute(
                "UPDATE users SET last_reward_claimed_at = NOW() WHERE id = %s",
                (user['id'],)
            )
            add_user_xp(cursor, user['id'], 20, 'daily_reward', 'Daily reward claimed')
            create_user_notification(cursor, user['id'], 'reward', 'Reward claimed', 'You earned 20 XP from the daily reward.')
            conn.commit()
            return jsonify({'success': True, 'xp_awarded': 20})
    except Exception as e:
        print(f"Error claiming reward: {e}")
        return jsonify({'error': 'Unable to claim reward'}), 500
    finally:
        conn.close()


@app.route('/api/favorites/toggle', methods=['POST'])
def toggle_favorite_user():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    favorite_user_id = payload.get('user_id')
    try:
        favorite_user_id = int(favorite_user_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid user'}), 400
    if favorite_user_id == int(user['id']):
        return jsonify({'error': 'You cannot save your own profile'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cursor:
            ensure_engagement_schema(cursor)
            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE id = %s
                  AND COALESCE(is_deleted, FALSE) = FALSE
                  AND COALESCE(is_blocked, FALSE) = FALSE
                  AND COALESCE(is_admin, FALSE) = FALSE
                LIMIT 1
                """,
                (favorite_user_id,)
            )
            if not cursor.fetchone():
                return jsonify({'error': 'Profile is not available'}), 404
            cursor.execute(
                "SELECT id FROM user_favorites WHERE user_id = %s AND favorite_user_id = %s LIMIT 1",
                (user['id'], favorite_user_id)
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute("DELETE FROM user_favorites WHERE id = %s", (existing['id'],))
                saved = False
            else:
                cursor.execute(
                    "INSERT INTO user_favorites (user_id, favorite_user_id) VALUES (%s, %s)",
                    (user['id'], favorite_user_id)
                )
                add_user_xp(cursor, user['id'], 3, 'favorite_user', 'Profile saved', favorite_user_id)
                saved = True
            conn.commit()
            return jsonify({'success': True, 'saved': saved})
    except Exception as e:
        print(f"Error toggling favorite: {e}")
        return jsonify({'error': 'Unable to update favorite'}), 500
    finally:
        conn.close()


@app.route('/saved-profiles')
@app.route('/api/saved-profiles')
@app.route('/api/favorites/list')
def list_favorite_users():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cursor:
            ensure_engagement_schema(cursor)
            cursor.execute(
                """
                SELECT f.id AS favorite_id, f.created_at,
                       u.id, u.username, u.full_name, u.location, u.avatar_url,
                       u.skills_offered, u.skills_wanted
                FROM user_favorites f
                JOIN users u ON u.id = f.favorite_user_id
                WHERE f.user_id = %s
                  AND COALESCE(u.is_deleted, FALSE) = FALSE
                  AND COALESCE(u.is_blocked, FALSE) = FALSE
                ORDER BY f.created_at DESC
                """,
                (user['id'],)
            )
            rows = cursor.fetchall()

        favorites = []
        for row in rows:
            other_user = {
                'skills_offered': row.get('skills_offered'),
                'skills_wanted': row.get('skills_wanted')
            }
            match_details = enrich_skill_match(user, other_user)
            favorites.append({
                'favorite_id': row['favorite_id'],
                'id': row['id'],
                'name': row['full_name'] or row['username'],
                'username': row['username'],
                'location': row['location'] or 'Remote',
                'avatar_url': normalize_avatar_url(row.get('avatar_url'), row.get('username')),
                'teaches': row.get('skills_offered') or '',
                'learns': row.get('skills_wanted') or '',
                'match_percentage': match_details['match_percentage'],
                'match_pairs': match_details['match_pairs'],
                'created_at': transform_timestamp(row['created_at'])
            })

        return jsonify({'favorites': favorites})
    except Exception as e:
        print(f"Error fetching saved profiles: {e}")
        return jsonify({'error': 'Unable to load saved profiles'}), 500
    finally:
        conn.close()


@app.route('/api/saved-profiles/remove', methods=['POST'])
@app.route('/api/favorites/remove', methods=['POST'])
def remove_favorite_user():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    favorite_user_id = payload.get('user_id')
    try:
        favorite_user_id = int(favorite_user_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid user'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cursor:
            ensure_engagement_schema(cursor)
            cursor.execute(
                "DELETE FROM user_favorites WHERE user_id = %s AND favorite_user_id = %s",
                (user['id'], favorite_user_id)
            )
            removed = cursor.rowcount > 0
            conn.commit()
            return jsonify({'success': True, 'removed': removed})
    except Exception as e:
        print(f"Error removing saved profile: {e}")
        return jsonify({'error': 'Unable to remove saved profile'}), 500
    finally:
        conn.close()


@app.route('/api/reviews/submit', methods=['POST'])
def submit_user_review():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    reviewed_user_id = payload.get('reviewed_user_id')
    rating = payload.get('rating')
    feedback = (payload.get('feedback') or '').strip()
    experience_tag = (payload.get('experience_tag') or '').strip()
    try:
        reviewed_user_id = int(reviewed_user_id)
        rating = int(rating)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid review details'}), 400
    if reviewed_user_id == int(user['id']) or rating < 1 or rating > 5:
        return jsonify({'error': 'Invalid review details'}), 400
    if len(feedback) > 500:
        return jsonify({'error': 'Feedback must be 500 characters or less'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cursor:
            ensure_engagement_schema(cursor)
            ensure_unfollow_report_schema(cursor)
            cursor.execute(
                f"""
                SELECT r.id
                FROM requests r
                WHERE r.status = 'accepted'
                  AND (
                    (r.sender_id = %s AND r.receiver_id = %s)
                    OR (r.sender_id = %s AND r.receiver_id = %s)
                  )
                  AND {active_relationship_filter_sql('r')}
                ORDER BY r.created_at DESC
                LIMIT 1
                """,
                (user['id'], reviewed_user_id, reviewed_user_id, user['id'])
            )
            req = cursor.fetchone()
            if not req:
                return jsonify({'error': 'Reviews are only available after an accepted skill exchange'}), 403
            cursor.execute(
                """
                INSERT INTO user_reviews (reviewer_id, reviewed_user_id, request_id, rating, feedback, experience_tag, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'visible')
                ON DUPLICATE KEY UPDATE
                    request_id = VALUES(request_id),
                    rating = VALUES(rating),
                    feedback = VALUES(feedback),
                    experience_tag = VALUES(experience_tag),
                    status = 'visible',
                    updated_at = NOW()
                """,
                (user['id'], reviewed_user_id, req['id'], rating, feedback, experience_tag)
            )
            add_user_xp(cursor, user['id'], 8, 'review_given', 'Review submitted', reviewed_user_id)
            create_user_notification(cursor, reviewed_user_id, 'review', 'New review', f'{user["username"]} reviewed your skill exchange.', req['id'])
            if rating >= 4:
                award_achievement(cursor, reviewed_user_id, 'helpful_user')
            create_admin_notification(
                cursor,
                'review',
                'New user review',
                f'{user["username"]} submitted a {rating}-star review.',
                related_id=req['id'],
                icon='fa-solid fa-star'
            )
            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        print(f"Error submitting review: {e}")
        return jsonify({'error': 'Unable to submit review'}), 500
    finally:
        conn.close()

@app.route('/api/request/send', methods=['POST'])
def send_request():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized' }), 401

    payload = request.get_json(silent=True) or {}
    receiver_id = payload.get('receiver_id')
    skill_requested = payload.get('skill_requested')
    skill_offered = payload.get('skill_offered')

    if not receiver_id or not skill_requested or not skill_offered:
        return jsonify({'error': 'receiver_id, skill_requested, and skill_offered are required'}), 400
    skill_requested = str(skill_requested).strip()
    skill_offered = str(skill_offered).strip()
    if not skill_requested or not skill_offered or len(skill_requested) > 120 or len(skill_offered) > 120:
        return jsonify({'error': 'Skill names must be 120 characters or less'}), 400

    try:
        receiver_id = int(receiver_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid receiver'}), 400

    if receiver_id == user['id']:
        return jsonify({'error': 'You cannot send a request to yourself'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_unfollow_report_schema(cursor)
            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE id = %s
                  AND COALESCE(is_deleted, FALSE) = FALSE
                  AND COALESCE(is_blocked, FALSE) = FALSE
                  AND COALESCE(is_admin, FALSE) = FALSE
                  AND COALESCE(profile_visibility, TRUE) = TRUE
                """,
                (receiver_id,)
            )
            if not cursor.fetchone():
                return jsonify({'error': 'Target user not found'}), 404

            relationship = get_relationship_state(cursor, user['id'], receiver_id)
            if not relationship.get('can_request'):
                return jsonify({
                    'success': True,
                    'already_exists': True,
                    'message': relationship['label'],
                    'relationship': relationship
                })

            cursor.execute(
                "INSERT INTO requests (sender_id, receiver_id, skill_requested, skill_offered, status, created_at) VALUES (%s, %s, %s, %s, 'pending', NOW())",
                (user['id'], receiver_id, skill_requested, skill_offered)
            )
            new_request_id = cursor.lastrowid
            relationship = {
                'status': 'pending',
                'label': 'Request Sent',
                'can_request': False,
                'request_id': new_request_id,
                'match_id': None,
            }
            create_admin_notification(
                cursor,
                'request',
                'New skill swap request',
                f'{user["username"]} requested {skill_requested} and offered {skill_offered}.',
                related_id=new_request_id,
                icon='fa-solid fa-handshake'
            )
            add_user_xp(cursor, user['id'], 10, 'request_sent', 'Skill request sent', new_request_id)
            create_user_notification(
                cursor,
                receiver_id,
                'request',
                'New skill request',
                f'{user["username"]} sent you a skill swap request.',
                new_request_id
            )
            conn.commit()
            return jsonify({'success': True, 'relationship': relationship})
    except Exception as e:
        print(f"Error saving request: {e}")
        return jsonify({'error': 'Unable to save request'}), 500
    finally:
        conn.close()


@app.route('/api/request/incoming')
def incoming_requests():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_unfollow_report_schema(cursor)
            cursor.execute(
                """
                SELECT r.id, r.sender_id, r.receiver_id, r.skill_requested, r.skill_offered, r.status, r.created_at, r.payment_status,
                       u.username, u.full_name, u.location, u.avatar_url,
                       u.skills_offered as sender_offers, u.skills_wanted as sender_wants
                FROM requests r
                JOIN users u ON u.id = r.sender_id
                WHERE r.receiver_id = %s
                  AND COALESCE(u.is_deleted, FALSE) = FALSE
                  AND COALESCE(u.is_blocked, FALSE) = FALSE
                  AND NOT EXISTS (
                    SELECT 1
                    FROM unfollow_reports ur
                    WHERE ur.request_id = r.id
                )
                ORDER BY r.created_at DESC
                """,
                (user['id'],)
            )
            rows = cursor.fetchall()

        items = []
        seen_users = set()
        for row in rows:
            if row['sender_id'] in seen_users:
                continue
            seen_users.add(row['sender_id'])
            other_user = {
                'skills_offered': row.get('sender_offers'),
                'skills_wanted': row.get('sender_wants')
            }
            match_details = enrich_skill_match(user, other_user)

            items.append({
                'id': row['id'],
                'sender_id': row['sender_id'],
                'name': row['full_name'] or row['username'],
                'username': row['username'],
                'role': row['skill_offered'] or 'Skill Mentor',
                'location': row['location'] or 'Remote',
                'learns': row['sender_wants'] or 'Learning',
                'teaches': row['sender_offers'] or 'Teaching',
                'status': row['status'],
                'payment_status': row['payment_status'] if 'payment_status' in row else 'pending',
                'created_at': transform_timestamp(row['created_at']),
                'avatar_url': normalize_avatar_url(row.get('avatar_url'), row.get('username')),
                'match_status': match_details['match_status'],
                'match_percentage': match_details['match_percentage'],
                'match_badge_variant': match_details['match_badge_variant'],
                'match_badge_label': match_details['match_badge_label'],
                'match_pairs': match_details['match_pairs'],
                'match_summary': match_details['match_summary'],
                'video_url': row.get('video_url', None)
            })

        return jsonify({'requests': items})
    except Exception as e:
        print(f"Error fetching incoming requests: {e}")
        return jsonify({'error': 'Unable to load incoming requests'}), 500
    finally:
        conn.close()


@app.route('/api/request/sent')
def sent_requests():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_unfollow_report_schema(cursor)
            cursor.execute(
                """
                SELECT r.id, r.sender_id, r.receiver_id, r.skill_requested, r.skill_offered, r.status, r.created_at,
                       u.username, u.full_name, u.location, u.avatar_url, u.video_url,
                       u.skills_wanted as receiver_wants, u.skills_offered as receiver_offers
                FROM requests r
                JOIN users u ON u.id = r.receiver_id
                WHERE r.sender_id = %s
                  AND COALESCE(u.is_deleted, FALSE) = FALSE
                  AND COALESCE(u.is_blocked, FALSE) = FALSE
                  AND NOT EXISTS (
                    SELECT 1
                    FROM unfollow_reports ur
                    WHERE ur.request_id = r.id
                )
                ORDER BY r.created_at DESC
                """,
                (user['id'],)
            )
            rows = cursor.fetchall()

        items = []
        seen_users = set()
        for row in rows:
            if row['receiver_id'] in seen_users:
                continue
            seen_users.add(row['receiver_id'])
            other_user = {
                'skills_offered': row.get('receiver_offers'),
                'skills_wanted': row.get('receiver_wants')
            }
            match_details = enrich_skill_match(user, other_user)

            items.append({
                'id': row['id'],
                'receiver_id': row['receiver_id'],
                'name': row['full_name'] or row['username'],
                'username': row['username'],
                'role': row['skill_offered'] or 'Skill Mentor',
                'location': row['location'] or 'Remote',
                'learns': row['receiver_wants'] or 'Learning',
                'teaches': row['receiver_offers'] or 'Teaching',
                'status': row['status'],
                'created_at': transform_timestamp(row['created_at']),
                'avatar_url': normalize_avatar_url(row.get('avatar_url'), row.get('username')),
                'match_status': match_details['match_status'],
                'match_percentage': match_details['match_percentage'],
                'match_badge_variant': match_details['match_badge_variant'],
                'match_badge_label': match_details['match_badge_label'],
                'match_pairs': match_details['match_pairs'],
                'match_summary': match_details['match_summary'],
                'video_url': row.get('video_url', None)
            })

        return jsonify({'requests': items})
    except Exception as e:
        print(f"Error fetching sent requests: {e}")
        return jsonify({'error': 'Unable to load sent requests'}), 500
    finally:
        conn.close()


@app.route('/api/request/accept', methods=['POST'])
def accept_request():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    request_id = payload.get('request_id')
    if not request_id:
        return jsonify({'error': 'request_id is required'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.sender_id, r.receiver_id, r.status, r.skill_requested, r.skill_offered,
                       sender.skills_offered AS sender_offers,
                       sender.skills_wanted AS sender_wants,
                       receiver.skills_offered AS receiver_offers,
                       receiver.skills_wanted AS receiver_wants
                FROM requests r
                JOIN users sender ON sender.id = r.sender_id
                JOIN users receiver ON receiver.id = r.receiver_id
                WHERE r.id = %s
                  AND r.receiver_id = %s
                  AND COALESCE(sender.is_deleted, FALSE) = FALSE
                  AND COALESCE(sender.is_blocked, FALSE) = FALSE
                """,
                (request_id, user['id'])
            )
            req = cursor.fetchone()
            if not req:
                return jsonify({'error': 'Request not found'}), 404
            cursor.execute(
                "SELECT id FROM unfollow_reports WHERE request_id = %s LIMIT 1",
                (request_id,)
            )
            if cursor.fetchone():
                return jsonify({'error': 'This request was removed or cancelled'}), 400
            if req['status'] != 'pending':
                return jsonify({'error': 'Only pending requests can be accepted'}), 400

            cursor.execute(
                "UPDATE requests SET status = 'accepted' WHERE id = %s",
                (request_id,)
            )
            create_admin_notification(
                cursor,
                'request',
                'Skill swap request accepted',
                f'Request #{request_id} was accepted.',
                related_id=request_id,
                icon='fa-solid fa-circle-check'
            )
            add_user_xp(cursor, user['id'], 15, 'request_accepted', 'Request accepted', request_id)
            add_user_xp(cursor, req['sender_id'], 15, 'request_accepted', 'Your request was accepted', request_id)
            create_user_notification(
                cursor,
                req['sender_id'],
                'request',
                'Request accepted',
                f'{user["username"]} accepted your skill swap request.',
                request_id
            )
            sender_user = {
                'skills_offered': req.get('sender_offers'),
                'skills_wanted': req.get('sender_wants')
            }
            receiver_user = {
                'skills_offered': req.get('receiver_offers'),
                'skills_wanted': req.get('receiver_wants')
            }
            if not is_two_way_match(receiver_user, sender_user):
                conn.commit()
                return jsonify({'success': True})
            cursor.execute(
                "SELECT id FROM matches WHERE (user1_id = %s AND user2_id = %s) OR (user1_id = %s AND user2_id = %s)",
                (req['sender_id'], req['receiver_id'], req['receiver_id'], req['sender_id'])
            )
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO matches (request_id, user1_id, user2_id, skill_exchange_details, matched_at) VALUES (%s, %s, %s, %s, NOW())",
                    (
                        request_id,
                        req['sender_id'],
                        req['receiver_id'],
                        f"{req['skill_offered']} ↔ {req['skill_requested']}"
                    )
                )
                award_achievement(cursor, req['sender_id'], 'first_match')
                award_achievement(cursor, req['receiver_id'], 'first_match')
                create_user_notification(cursor, req['sender_id'], 'match', 'New match', 'You have a new SkillFlow match.', request_id)
                create_user_notification(cursor, req['receiver_id'], 'match', 'New match', 'You have a new SkillFlow match.', request_id)
            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        print(f"Error accepting request: {e}")
        return jsonify({'error': 'Unable to accept request'}), 500
    finally:
        conn.close()


@app.route('/api/request/reject', methods=['POST'])
def reject_request():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    request_id = payload.get('request_id')
    if not request_id:
        return jsonify({'error': 'request_id is required'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_unfollow_report_schema(cursor)
            cursor.execute(
                """
                SELECT r.status
                FROM requests r
                JOIN users sender ON sender.id = r.sender_id
                WHERE r.id = %s
                  AND r.receiver_id = %s
                  AND COALESCE(sender.is_deleted, FALSE) = FALSE
                  AND COALESCE(sender.is_blocked, FALSE) = FALSE
                """,
                (request_id, user['id'])
            )
            req = cursor.fetchone()
            if not req:
                return jsonify({'error': 'Request not found'}), 404
            cursor.execute(
                "SELECT id FROM unfollow_reports WHERE request_id = %s LIMIT 1",
                (request_id,)
            )
            if cursor.fetchone():
                return jsonify({'error': 'This request was removed or cancelled'}), 400
            if req['status'] != 'pending':
                return jsonify({'error': 'Only pending requests can be rejected'}), 400

            cursor.execute(
                "UPDATE requests SET status = 'rejected' WHERE id = %s",
                (request_id,)
            )
            create_admin_notification(
                cursor,
                'request',
                'Skill swap request rejected',
                f'Request #{request_id} was rejected.',
                related_id=request_id,
                icon='fa-solid fa-circle-xmark'
            )
            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        print(f"Error rejecting request: {e}")
        return jsonify({'error': 'Unable to reject request'}), 500
    finally:
        conn.close()


@app.route('/api/matches')
def get_matches():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_unfollow_report_schema(cursor)
            ensure_payment_schema(cursor)
            expire_chat_access(cursor)
            conn.commit()
            current_user_paid = bool(get_user_chat_subscription(cursor, user['id']))

            cursor.execute(
                """
                SELECT
                       m.id AS match_id,
                       r.id AS request_id,
                       COALESCE(m.skill_exchange_details, CONCAT(r.skill_offered, ' ↔ ', r.skill_requested)) AS skill_exchange_details,
                       COALESCE(m.matched_at, r.created_at) AS matched_at,
                       r.status AS request_status,
                       r.payment_status,
                       %s AS current_user_paid,
                       IF(r.sender_id = %s, r.receiver_id, r.sender_id) AS other_id,
                       u.username, u.full_name, u.location, u.avatar_url, u.video_url, u.phone, u.email, u.contact_sharing,
                       u.skills_offered AS other_offers,
                       u.skills_wanted AS other_wants
                FROM requests r
                JOIN users u ON u.id = IF(r.sender_id = %s, r.receiver_id, r.sender_id)
                LEFT JOIN matches m
                  ON m.request_id = r.id
                  OR (
                    m.request_id IS NULL
                    AND ((m.user1_id = r.sender_id AND m.user2_id = r.receiver_id)
                      OR (m.user1_id = r.receiver_id AND m.user2_id = r.sender_id))
                  )
                WHERE %s IN (r.sender_id, r.receiver_id)
                  AND r.status IN ('accepted', 'pending')
                  AND COALESCE(u.is_deleted, FALSE) = FALSE
                  AND COALESCE(u.is_blocked, FALSE) = FALSE
                  AND NOT EXISTS (
                    SELECT 1
                    FROM unfollow_reports ur
                    WHERE ur.request_id = r.id
                  )
                ORDER BY
                  CASE WHEN r.status = 'accepted' THEN 0 ELSE 1 END,
                  COALESCE(m.matched_at, r.created_at) DESC
                """,
                (current_user_paid, user['id'], user['id'], user['id'])
            )
            rows = cursor.fetchall()

        items = []
        seen_users = set()
        for row in rows:
            if row['other_id'] in seen_users:
                continue
            other_user = {
                'skills_offered': row.get('other_offers'),
                'skills_wanted': row.get('other_wants')
            }
            match_details = enrich_skill_match(user, other_user)
            is_accepted = (row.get('request_status') or '').lower() == 'accepted'
            has_skill_match = bool(match_details['match_pairs'])
            if not is_accepted and not has_skill_match:
                continue
            seen_users.add(row['other_id'])
            current_user_paid = bool(row.get('current_user_paid'))

            items.append({
                'id': row.get('match_id') or row['request_id'],
                'request_id': row['request_id'],
                'request_status': row.get('request_status') or 'accepted',
                'can_chat': is_accepted,
                'payment_status': row['payment_status'] or 'pending',
                'other_id': row['other_id'],
                'name': row['full_name'] or row['username'],
                'username': row['username'],
                'role': 'Matched Skill Partner' if is_accepted else 'Skill Match',
                'location': row['location'] or 'Remote',
                'exchange': row['skill_exchange_details'] or 'Skill Exchange',
                'match_status': match_details['match_status'],
                'match_percentage': match_details['match_percentage'],
                'match_badge_variant': match_details['match_badge_variant'],
                'match_badge_label': match_details['match_badge_label'],
                'match_pairs': match_details['match_pairs'],
                'match_summary': match_details['match_summary'],
                'matched_at': transform_timestamp(row['matched_at']),
                'avatar_url': normalize_avatar_url(row.get('avatar_url'), row.get('username')),
                'video_url': row.get('video_url', None),
                'phone': row['phone'] if (row.get('contact_sharing') and current_user_paid) else None,
                'email': row['email'] if (row.get('contact_sharing') and current_user_paid) else None
            })

        print(f"[Matches Debug] user_id={user['id']} rows={len(rows)} rendered={len(items)}")
        return jsonify({'matches': items})
    except Exception as e:
        print(f"Error fetching matches: {e}")
        return jsonify({'error': 'Unable to load matches'}), 500
    finally:
        conn.close()


@app.route('/api/chat/unfollow', methods=['POST'])
def chat_unfollow():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    request_id = payload.get('request_id')
    target_user_id = payload.get('user_id')
    reason = (payload.get('reason') or '').strip()
    custom_reason = (payload.get('custom_reason') or '').strip()
    allowed_reasons = {
        'Teaching style not helpful',
        'Skill mismatch',
        'Not active',
        'Skills not matching',
        'Not interested anymore',
        'User inactive',
        'Communication issue',
        'Found better skill partner',
        'Wrong request sent',
        'Other',
    }

    if not request_id or not target_user_id:
        return jsonify({'success': False, 'error': 'Missing chat details'}), 400
    if reason not in allowed_reasons:
        return jsonify({'success': False, 'error': 'Please select a valid reason'}), 400
    if reason == 'Other' and not custom_reason:
        return jsonify({'success': False, 'error': 'Please add a reason in Other'}), 400

    try:
        request_id = int(request_id)
        target_user_id = int(target_user_id)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Invalid chat details'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Database connection failed'}), 500

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, sender_id, receiver_id, status
                FROM requests
                WHERE id = %s
                  AND (sender_id = %s OR receiver_id = %s)
                LIMIT 1
                """,
                (request_id, user['id'], user['id'])
            )
            req = cursor.fetchone()
            if not req:
                return jsonify({'success': False, 'error': 'Chat connection not found'}), 404
            if (req.get('status') or '').lower() != 'accepted':
                return jsonify({'success': False, 'error': 'Only accepted chats can be unfollowed'}), 400

            other_user_id = req['receiver_id'] if int(req['sender_id']) == int(user['id']) else req['sender_id']
            if int(other_user_id) != int(target_user_id):
                return jsonify({'success': False, 'error': 'This chat does not belong to the selected user'}), 403

            report_saved = insert_unfollow_report_safely(cursor, {
                'match_id': None,
                'request_id': request_id,
                'unfollower_id': user['id'],
                'unfollowed_user_id': other_user_id,
                'action_type': 'unfollow',
                'previous_request_status': req.get('status'),
                'reason': reason,
                'custom_reason': custom_reason or None,
                'status': 'pending',
            })
            if not report_saved:
                cursor.execute(
                    "UPDATE requests SET status = 'rejected' WHERE id = %s AND status = 'accepted'",
                    (request_id,)
                )

            if table_exists(cursor, 'matches') and column_exists(cursor, 'matches', 'request_id'):
                cursor.execute("DELETE FROM matches WHERE request_id = %s", (request_id,))

            conn.commit()
            return jsonify({'success': True, 'message': 'Match removed successfully'})
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"Chat unfollow error: {type(e).__name__}: {e}; payload={payload}; user_id={user.get('id') if user else None}")
        return jsonify({'success': False, 'error': 'Unable to remove match'}), 500
    finally:
        conn.close()


@app.route('/api/request/cancel', methods=['POST'])
def cancel_request():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    request_id = payload.get('request_id')
    reason = (payload.get('reason') or '').strip()
    custom_reason = (payload.get('custom_reason') or '').strip()
    allowed_reasons = {
        'Skill mismatch',
        'Not active',
        'Skills not matching',
        'Not interested anymore',
        'Communication issue',
        'User inactive',
        'Found better skill partner',
        'Wrong request sent',
        'Other',
    }

    if not request_id:
        return jsonify({'error': 'request_id is required'}), 400
    if reason not in allowed_reasons:
        return jsonify({'error': 'Please select a valid reason'}), 400
    if reason == 'Other' and not custom_reason:
        return jsonify({'error': 'Please add a reason in Other'}), 400

    try:
        request_id = int(request_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid request'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_unfollow_report_schema(cursor)
            cursor.execute(
                """
                SELECT r.id, r.sender_id, r.receiver_id, r.status,
                       sender.username AS unfollower_username,
                       receiver.username AS unfollowed_username
                FROM requests r
                JOIN users sender ON sender.id = r.sender_id
                JOIN users receiver ON receiver.id = r.receiver_id
                WHERE r.id = %s
                  AND r.sender_id = %s
                LIMIT 1
                """,
                (request_id, user['id'])
            )
            req = cursor.fetchone()
            if not req:
                return jsonify({'error': 'Request not found'}), 404
            if req['status'] != 'pending':
                return jsonify({'error': 'Only pending sent requests can be cancelled'}), 400

            cursor.execute(
                """
                INSERT INTO unfollow_reports (
                    match_id, request_id, unfollower_id, unfollowed_user_id,
                    action_type, previous_request_status, reason, custom_reason, status, created_at
                )
                VALUES (NULL, %s, %s, %s, 'cancel_request', %s, %s, %s, 'pending', NOW())
                """,
                (request_id, user['id'], req['receiver_id'], req['status'], reason, custom_reason or None)
            )
            create_admin_notification(
                cursor,
                'request',
                'Request cancelled',
                f'{req.get("unfollower_username")} cancelled request to {req.get("unfollowed_username")} ({reason}).',
                related_id=request_id,
                icon='fa-solid fa-ban'
            )
            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        print(f"Error cancelling request: {e}")
        return jsonify({'error': 'Unable to cancel request'}), 500
    finally:
        conn.close()

@app.route('/api/chat/list')
def chat_list():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_unfollow_report_schema(cursor)
            expire_chat_access(cursor)
            conn.commit()

            cursor.execute(
                """
                SELECT r.id AS request_id, r.sender_id, r.receiver_id, r.skill_requested, r.skill_offered,
                       r.status AS request_status, r.payment_status, r.payment_date, r.expiry_date, r.created_at,
                       u.id AS other_id, u.username, u.full_name, u.location, u.avatar_url,
                       u.phone, u.email, u.contact_sharing,
                       (
                           SELECT COALESCE(message_text, content)
                           FROM messages msg
                           WHERE msg.request_id = r.id
                           ORDER BY msg.created_at DESC
                           LIMIT 1
                       ) AS last_message,
                       (
                           SELECT created_at
                           FROM messages msg
                           WHERE msg.request_id = r.id
                           ORDER BY msg.created_at DESC
                           LIMIT 1
                       ) AS last_message_at
                FROM requests r
                JOIN users u ON u.id = IF(r.sender_id = %s, r.receiver_id, r.sender_id)
                WHERE r.status = 'accepted'
                  AND %s IN (r.sender_id, r.receiver_id)
                  AND COALESCE(u.is_deleted, FALSE) = FALSE
                  AND COALESCE(u.is_blocked, FALSE) = FALSE
                  AND NOT EXISTS (
                    SELECT 1
                    FROM unfollow_reports ur
                    WHERE ur.request_id = r.id
                  )
                ORDER BY COALESCE(last_message_at, r.created_at) DESC
                """,
                (user['id'], user['id'])
            )
            rows = cursor.fetchall()

            chats = []
            for row in rows:
                request_status = row.get('request_status') or 'pending'
                payment_status = row.get('payment_status') or 'pending'
                chat_request = {
                    'id': row.get('request_id'),
                    'sender_id': row.get('sender_id'),
                    'receiver_id': row.get('receiver_id'),
                    'status': request_status,
                    'payment_status': payment_status,
                    'expiry_date': row.get('expiry_date')
                }
                access_state = get_chat_access_state(cursor, chat_request, user['id'])
                is_unlocked = access_state['is_unlocked']
                status_label = 'Premium Active' if is_unlocked else ('Waiting' if access_state['current_user_paid'] else 'Locked')
                chats.append({
                    'request_id': row['request_id'],
                    'other_id': row['other_id'],
                    'name': row['full_name'] or row['username'],
                    'username': row['username'],
                    'location': row['location'] or 'Remote',
                    'avatar_url': normalize_avatar_url(row.get('avatar_url'), row.get('username')),
                    'request_status': request_status,
                    'payment_status': 'paid' if is_unlocked else payment_status,
                    'is_unlocked': is_unlocked,
                    'current_user_paid': access_state['current_user_paid'],
                    'other_user_paid': access_state['other_user_paid'],
                    'status_label': status_label,
                    'lock_message': access_state['lock_message'],
                    'unlock_date': transform_timestamp(access_state.get('unlock_date') or row.get('payment_date')),
                    'expiry_date': transform_timestamp(access_state.get('expiry_date') or row.get('expiry_date')),
                    'last_message': row.get('last_message') or status_label,
                    'last_message_at': transform_timestamp(row.get('last_message_at')),
                    'phone': row['phone'] if (row.get('contact_sharing') and is_unlocked) else None,
                    'email': row['email'] if (row.get('contact_sharing') and is_unlocked) else None
                })

        return jsonify({'chats': chats})
    except Exception as e:
        print(f"Error fetching chat list: {e}")
        return jsonify({'error': 'Unable to load chats'}), 500
    finally:
        conn.close()

@app.route('/api/payment/create', methods=['POST'])
def create_payment():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    request_id = payload.get('request_id')
    
    if not request_id:
        return jsonify({'error': 'request_id is required'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    amount_rupees = get_chat_unlock_price_rupees()
    amount = int(round(amount_rupees * 100))
    merchant_order_id = None
    try:
        with conn.cursor() as cursor:
            ensure_premium_schema(cursor)
            ensure_unfollow_report_schema(cursor)
            req = get_chat_request(cursor, request_id, user['id'])
            conn.commit()
            if not req:
                return jsonify({'error': 'Chat request not found'}), 404
            cursor.execute(
                "SELECT id FROM unfollow_reports WHERE request_id = %s LIMIT 1",
                (request_id,)
            )
            if cursor.fetchone():
                return jsonify({'error': 'This match was removed.'}), 400
            if req['status'] != 'accepted':
                return jsonify({'error': 'Request must be accepted before unlocking chat'}), 400
            if has_user_chat_unlock(cursor, user['id'], request_id):
                return jsonify({
                    'success': True,
                    'premium_active': True,
                    'already_paid': True,
                    'redirect_url': url_for('chat_page', request_id=request_id, payment_status='success')
                })

        merchant_order_id = f'SF{request_id}{int(datetime.utcnow().timestamp())}'
        redirect_path = url_for(
            'verify_payment',
            request_id=request_id,
            merchant_order_id=merchant_order_id
        )
        # For PhonePe callbacks, prefer the current request host. Set
        # PUBLIC_BASE_URL only when the app is behind a proxy that hides it.
        redirect_url = f'{PUBLIC_BASE_URL}{redirect_path}' if PUBLIC_BASE_URL else url_for(
            'verify_payment',
            request_id=request_id,
            merchant_order_id=merchant_order_id,
            _external=True
        )
        print("[PhonePe Config Debug]", phonepe_config_snapshot())
        print("[PhonePe Create Debug]", {
            'user_id': user['id'],
            'request_id': request_id,
            'merchant_order_id': merchant_order_id,
            'amount_paise': amount,
            'redirect_url': redirect_url,
        })
        phonepe_config = get_phonepe_runtime_config()

        with conn.cursor() as cursor:
            save_phonepe_payment(
                cursor,
                user['id'],
                request_id,
                amount_rupees,
                merchant_order_id,
                status='created',
                payment_status='pending'
            )
            conn.commit()

        access_token = get_phonepe_access_token(phonepe_config)
        create_payload = {
            'merchantOrderId': merchant_order_id,
            'amount': amount,
            'expireAfter': 1200,
            'metaInfo': {
                'udf1': f'user_{user["id"]}',
                'udf2': f'request_{request_id}',
                'udf3': 'Chat Access - 3 Months',
            },
            'paymentFlow': {
                'type': 'PG_CHECKOUT',
                'message': 'Chat Access - 3 Months',
                'merchantUrls': {'redirectUrl': redirect_url},
            },
        }
        print("[PhonePe Create Payload]", create_payload)

        # PhonePe API request: create a hosted sandbox checkout URL for this chat unlock.
        phonepe_response = requests.post(
            f'{phonepe_config["base_url"]}/checkout/v2/pay',
            json=create_payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'O-Bearer {access_token}',
            },
            timeout=20,
        )
        print("PhonePe Create Status:", phonepe_response.status_code)
        print("PhonePe Create Response:", phonepe_response.text)
        phonepe_response.raise_for_status()
        payment_data = phonepe_response.json()
        # PhonePe API response: extract the hosted checkout URL returned by sandbox.
        payment_url = extract_phonepe_redirect_url(payment_data)
        if not payment_url:
            raise RuntimeError('PhonePe checkout URL missing in response')

        return jsonify({
            'gateway': 'phonepe',
            'merchant_order_id': merchant_order_id,
            'amount': amount,
            'payment_url': payment_url
        })
    except requests.exceptions.HTTPError as e:
        response = e.response
        print(f"PhonePe HTTP Error: {e}")
        traceback.print_exc()
        if merchant_order_id:
            try:
                with conn.cursor() as cursor:
                    save_phonepe_payment(cursor, user['id'], request_id, amount_rupees, merchant_order_id, status='failed', payment_status='failed')
                    create_admin_notification(
                        cursor,
                        'payment',
                        'Payment creation failed',
                        f'PhonePe checkout failed for request #{request_id}.',
                        related_id=request_id,
                        icon='fa-solid fa-triangle-exclamation'
                    )
                    conn.commit()
            except Exception as db_error:
                print(f"[PhonePe DB Debug] Unable to mark create HTTP failure: {db_error}")
        return phonepe_error_response(
            'Payment gateway HTTP error',
            500,
            exception=str(e),
            phonepe_status_code=response.status_code if response is not None else None,
            phonepe_response=response.text if response is not None else None
        )
    except requests.exceptions.RequestException as e:
        print(f"PhonePe Request Error: {e}")
        traceback.print_exc()
        if merchant_order_id:
            try:
                with conn.cursor() as cursor:
                    save_phonepe_payment(cursor, user['id'], request_id, amount_rupees, merchant_order_id, status='failed', payment_status='failed')
                    create_admin_notification(
                        cursor,
                        'payment',
                        'Payment gateway request failed',
                        f'PhonePe request failed for request #{request_id}.',
                        related_id=request_id,
                        icon='fa-solid fa-triangle-exclamation'
                    )
                    conn.commit()
            except Exception as db_error:
                print(f"[PhonePe DB Debug] Unable to mark create request failure: {db_error}")
        return phonepe_error_response('Payment gateway request error', 500, exception=str(e))
    except Exception as e:
        print(f"PhonePe Error: {e}")
        traceback.print_exc()
        if merchant_order_id:
            try:
                with conn.cursor() as cursor:
                    save_phonepe_payment(cursor, user['id'], request_id, amount_rupees, merchant_order_id, status='failed', payment_status='failed')
                    create_admin_notification(
                        cursor,
                        'payment',
                        'Payment gateway error',
                        f'PhonePe checkout could not be created for request #{request_id}.',
                        related_id=request_id,
                        icon='fa-solid fa-triangle-exclamation'
                    )
                    conn.commit()
            except Exception as db_error:
                print(f"[PhonePe DB Debug] Unable to mark create failure: {db_error}")
        return phonepe_error_response('Payment gateway error', 500, exception=str(e))
    finally:
        conn.close()

@app.route('/api/payment/callback', methods=['GET', 'POST'])
@app.route('/api/payment/verify', methods=['GET', 'POST'])
def verify_payment():
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    request_id = payload.get('request_id') or request.args.get('request_id')
    merchant_order_id = (
        payload.get('merchant_order_id')
        or payload.get('merchantOrderId')
        or payload.get('orderId')
        or request.args.get('merchant_order_id')
        or request.args.get('merchantOrderId')
        or request.args.get('orderId')
    )
    if not request_id and merchant_order_id and merchant_order_id.startswith('req_'):
        request_id = merchant_order_id.split('_')[1]
    payment_user_id = user['id'] if user else None

    try:
        if not request_id or not merchant_order_id:
            raise ValueError('Missing PhonePe payment reference')

        print("[PhonePe Verify Debug]", {
            'logged_in_user_id': payment_user_id,
            'request_id': request_id,
            'merchant_order_id': merchant_order_id,
            'method': request.method,
            'args': request.args.to_dict(),
        })

        if not payment_user_id:
            lookup_conn = get_db_connection()
            if lookup_conn:
                try:
                    with lookup_conn.cursor() as cursor:
                        ensure_payment_schema(cursor)
                        cursor.execute(
                            """
                            SELECT user_id, request_id
                            FROM payments
                            WHERE merchant_order_id = %s
                            ORDER BY id DESC
                            LIMIT 1
                            """,
                            (merchant_order_id,)
                        )
                        payment_row = cursor.fetchone()
                        if payment_row:
                            payment_user_id = payment_row['user_id']
                            if request_id and int(request_id) != int(payment_row['request_id']):
                                raise ValueError('Payment reference does not match this chat request')
                            request_id = payment_row['request_id']
                finally:
                    lookup_conn.close()

        if not payment_user_id:
            if request.method == 'GET':
                flash('Please log in to verify payment.', 'error')
                return redirect(url_for('auth_page'))
            return jsonify({'error': 'Unauthorized'}), 401

        owner_conn = get_db_connection()
        if owner_conn:
            try:
                with owner_conn.cursor() as cursor:
                    ensure_payment_schema(cursor)
                    cursor.execute(
                        """
                        SELECT user_id, request_id
                        FROM payments
                        WHERE merchant_order_id = %s
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (merchant_order_id,)
                    )
                    payment_owner = cursor.fetchone()
                    if payment_owner:
                        if int(payment_owner['user_id']) != int(payment_user_id):
                            raise ValueError('Payment reference does not belong to the current user')
                        if int(payment_owner['request_id']) != int(request_id):
                            raise ValueError('Payment reference does not match this chat request')
            finally:
                owner_conn.close()

        phonepe_config = get_phonepe_runtime_config()
        access_token = get_phonepe_access_token(phonepe_config)
        # PhonePe verification request: confirm final order status before unlocking chat.
        status_response = requests.get(
            f'{phonepe_config["base_url"]}/checkout/v2/order/{merchant_order_id}/status',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'O-Bearer {access_token}',
            },
            timeout=20,
        )
        print("PhonePe Status API Code:", status_response.status_code)
        print("PhonePe Status API Response:", status_response.text)
        status_response.raise_for_status()
        status_data = status_response.json()
        # PhonePe verification response: only COMPLETED/SUCCESS states unlock the chat.
        payment_state = extract_phonepe_payment_state(status_data)
        if not is_phonepe_success_state(payment_state):
            fail_conn = get_db_connection()
            if fail_conn:
                try:
                    with fail_conn.cursor() as cursor:
                        save_phonepe_payment(cursor, payment_user_id, request_id, get_chat_unlock_price_rupees(), merchant_order_id, status='failed', payment_status=str(payment_state or 'failed').lower())
                        create_admin_notification(
                            cursor,
                            'payment',
                            'Payment failed',
                            f'PhonePe payment for request #{request_id} ended with {payment_state or "failed"}.',
                            related_id=request_id,
                            icon='fa-solid fa-circle-xmark'
                        )
                        fail_conn.commit()
                finally:
                    fail_conn.close()
            # Payment failure handling: leave the chat locked when PhonePe does not report success.
            raise ValueError(f'PhonePe payment is not successful: {payment_state}')
        payment_id = extract_phonepe_payment_id(status_data) or merchant_order_id
        
        conn = get_db_connection()
        if not conn:
            if request.method == 'GET':
                return redirect(url_for('chat_page', request_id=request_id, payment_status='failed'))
            return jsonify({'error': 'Database connection failed'}), 500

        try:
            with conn.cursor() as cursor:
                ensure_premium_schema(cursor)
                req = get_chat_request(cursor, request_id, payment_user_id)
                if not req:
                    if request.method == 'GET':
                        flash('Chat request not found.', 'error')
                        return redirect(url_for('requests_page'))
                    return jsonify({'error': 'Chat request not found'}), 404
                if req['status'] != 'accepted':
                    if request.method == 'GET':
                        flash('Request must be accepted before unlocking chat.', 'error')
                        return redirect(url_for('requests_page'))
                    return jsonify({'error': 'Request must be accepted before unlocking chat'}), 400

                cursor.execute(
                    """
                    UPDATE requests
                    SET payment_status = 'paid', payment_date = NOW(), expiry_date = NOW() + INTERVAL 90 DAY
                    WHERE status = 'accepted' AND %s IN (sender_id, receiver_id)
                    """,
                    (payment_user_id,)
                )
                if cursor.rowcount == 0:
                    if request.method == 'GET':
                        flash('Unable to unlock this chat request.', 'error')
                        return redirect(url_for('requests_page'))
                    return jsonify({'error': 'Unable to unlock this chat request'}), 400
                # Payment success handling: save the PhonePe transaction and unlock chat access for 90 days.
                save_phonepe_payment(
                    cursor,
                    payment_user_id,
                    request_id,
                    get_chat_unlock_price_rupees(),
                    merchant_order_id,
                    transaction_id=payment_id,
                    status='successful',
                    payment_status='paid'
                )
                cursor.execute(
                    """
                    UPDATE payments
                    SET premium_start_date = NOW(),
                        premium_expiry_date = NOW() + INTERVAL 90 DAY,
                        updated_at = NOW()
                    WHERE merchant_order_id = %s AND user_id = %s
                    """,
                    (merchant_order_id, payment_user_id)
                )
                cursor.execute(
                    """
                    UPDATE users
                    SET is_premium = TRUE,
                        premium_unlocked_at = NOW(),
                        premium_expiry_date = NOW() + INTERVAL 90 DAY
                    WHERE id = %s
                    """,
                    (payment_user_id,)
                )
                award_achievement(cursor, payment_user_id, 'premium_user')
                add_user_xp(cursor, payment_user_id, 25, 'premium_unlock', 'Premium chat unlocked', request_id)
                create_user_notification(
                    cursor,
                    payment_user_id,
                    'premium',
                    'Premium Active',
                    'Your premium chat access is active for 90 days.',
                    request_id
                )
                create_admin_notification(
                    cursor,
                    'payment',
                    'Payment successful',
                    f'PhonePe payment completed for request #{request_id}.',
                    related_id=request_id,
                    icon='fa-solid fa-circle-check'
                )
                create_admin_notification(
                    cursor,
                    'chat',
                    'Chat unlock event',
                    f'Chat access unlocked for request #{request_id}.',
                    related_id=request_id,
                    icon='fa-solid fa-unlock'
                )
            conn.commit()
        finally:
            conn.close()

        if request.method == 'GET':
            return redirect(url_for('chat_page', request_id=request_id, payment_status='success'))
        return jsonify({'success': True, 'redirect_url': url_for('chat_page', request_id=request_id, payment_status='success')})
    except Exception as e:
        print(f"Payment Verification Failed: {e}")
        traceback.print_exc()
        if request.method == 'GET':
            return redirect(url_for('chat_page', request_id=request_id, payment_status='failed') if request_id else url_for('requests_page'))
        return jsonify({'error': 'Payment verification failed'}), 400

@app.route('/api/chat/history')
def chat_history():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    request_id = request.args.get('request_id')
    if not request_id:
        return jsonify({'error': 'request_id is required'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_unfollow_report_schema(cursor)
            expire_chat_access(cursor, request_id)
            conn.commit()

            req = get_chat_request(cursor, request_id, user['id'])
            conn.commit()
            participant_ids = (int(req['sender_id']), int(req['receiver_id'])) if req else ()
            if not req or int(user['id']) not in participant_ids:
                return jsonify({'error': 'Unauthorized to view this chat'}), 403
            cursor.execute(
                "SELECT id FROM unfollow_reports WHERE request_id = %s LIMIT 1",
                (request_id,)
            )
            if cursor.fetchone():
                return jsonify({'error': 'This match was removed.'}), 403
            access_state = get_chat_access_state(cursor, req, user['id'])
            if not access_state['is_unlocked']:
                return jsonify({
                    'error': access_state['lock_message'],
                    'request_status': req.get('status'),
                    'payment_status': req.get('payment_status'),
                    'current_user_paid': access_state['current_user_paid'],
                    'other_user_paid': access_state['other_user_paid'],
                    'is_unlocked': False
                }), 403

            ensure_chat_attachment_schema(cursor)
            cursor.execute(
                """
                SELECT id, sender_id, receiver_id, COALESCE(message_text, content) AS message_text,
                       attachment_name, attachment_path, attachment_type, is_read, created_at
                FROM messages
                WHERE request_id = %s
                ORDER BY created_at ASC
                """,
                (request_id,)
            )
            rows = cursor.fetchall()
            cursor.execute(
                "UPDATE messages SET is_read = 1 WHERE request_id = %s AND receiver_id = %s",
                (request_id, user['id'])
            )
            conn.commit()

        history = []
        for row in rows:
            history.append({
                'id': row['id'],
                'sender_id': row['sender_id'],
                'receiver_id': row['receiver_id'],
                'message_text': row['message_text'],
                'content': row['message_text'],
                'attachment_name': row.get('attachment_name'),
                'attachment_type': row.get('attachment_type'),
                'attachment_url': url_for('static', filename=row['attachment_path']) if row.get('attachment_path') else None,
                'is_read': row.get('is_read', 0),
                'created_at': transform_timestamp(row['created_at'])
            })
        return jsonify({'messages': history, 'is_unlocked': True})
    except Exception as e:
        print(f"Error fetching chat history: {e}")
        return jsonify({'error': 'Unable to load chat history'}), 500
    finally:
        conn.close()

@app.route('/api/chat/send', methods=['POST'])
def chat_send():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    is_multipart = request.content_type and request.content_type.startswith('multipart/form-data')
    payload = {} if is_multipart else (request.get_json(silent=True) or {})
    request_id = request.form.get('request_id') if is_multipart else payload.get('request_id')
    content = ((request.form.get('content') if is_multipart else payload.get('content')) or '').strip()
    receiver_id = request.form.get('receiver_id') if is_multipart else payload.get('receiver_id')
    attachment = request.files.get('attachment') if is_multipart else None

    if not request_id or not receiver_id or (not content and not attachment):
        return jsonify({'error': 'request_id, receiver_id, and message or attachment are required'}), 400
    if len(content) > 2000:
        return jsonify({'error': 'Message must be 2000 characters or less'}), 400

    try:
        receiver_id = int(receiver_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid message receiver'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_unfollow_report_schema(cursor)
            ensure_chat_attachment_schema(cursor)
            expire_chat_access(cursor, request_id)
            conn.commit()

            req = get_chat_request(cursor, request_id, user['id'])
            conn.commit()
            participant_ids = (int(req['sender_id']), int(req['receiver_id'])) if req else ()
            if not req or int(user['id']) not in participant_ids:
                return jsonify({'error': 'Unauthorized to send message'}), 403
            cursor.execute(
                "SELECT id FROM unfollow_reports WHERE request_id = %s LIMIT 1",
                (request_id,)
            )
            if cursor.fetchone():
                return jsonify({'error': 'This match was removed.'}), 403
            access_state = get_chat_access_state(cursor, req, user['id'])
            if not access_state['is_unlocked']:
                return jsonify({
                    'error': access_state['lock_message'],
                    'request_status': req.get('status'),
                    'payment_status': req.get('payment_status'),
                    'current_user_paid': access_state['current_user_paid'],
                    'other_user_paid': access_state['other_user_paid'],
                    'is_unlocked': False
                }), 403

            if receiver_id not in participant_ids or receiver_id == int(user['id']):
                return jsonify({'error': 'Invalid message receiver'}), 400

            attachment_name = None
            attachment_path = None
            attachment_type = None
            if attachment and attachment.filename:
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'doc', 'docx', 'txt', 'zip'}
                original_name = secure_filename(attachment.filename)
                extension = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else ''
                if extension not in allowed_extensions:
                    return jsonify({'error': 'Unsupported attachment type'}), 400

                attachment.seek(0, os.SEEK_END)
                file_size = attachment.tell()
                attachment.seek(0)
                if file_size > 10 * 1024 * 1024:
                    return jsonify({'error': 'Attachment must be 10MB or smaller'}), 400

                upload_dir = os.path.join(app.static_folder, 'uploads', 'chat_files')
                os.makedirs(upload_dir, exist_ok=True)
                saved_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(6)}_{original_name}"
                attachment.save(os.path.join(upload_dir, saved_name))
                attachment_name = original_name
                attachment_path = f"uploads/chat_files/{saved_name}"
                attachment_type = attachment.mimetype or extension

            cursor.execute(
                """
                INSERT INTO messages
                    (request_id, sender_id, receiver_id, content, message_text, attachment_name, attachment_path, attachment_type, is_read, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, NOW())
                """,
                (request_id, user['id'], receiver_id, content, content, attachment_name, attachment_path, attachment_type)
            )
            add_user_xp(cursor, user['id'], 2, 'chat_message', 'Chat message sent', request_id)
            cursor.execute(
                "SELECT COUNT(*) AS count FROM messages WHERE sender_id = %s",
                (user['id'],)
            )
            if int((cursor.fetchone() or {}).get('count') or 0) >= 5:
                award_achievement(cursor, user['id'], 'five_skill_chats')
            create_user_notification(
                cursor,
                receiver_id,
                'message',
                'Unread message',
                f'{user["username"]} sent you a message.',
                request_id
            )
            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        print(f"Error sending message: {e}")
        return jsonify({'error': 'Unable to send message'}), 500
    finally:
        conn.close()

@app.route('/api/profile/update', methods=['POST'])
def profile_update():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    username = normalize_username(payload.get('username', user.get('username')))
    full_name = payload.get('full_name')
    location = payload.get('location')
    skills_offered = payload.get('skills_offered')
    skills_wanted = payload.get('skills_wanted')
    bio = payload.get('bio')
    phone = payload.get('phone')
    contact_number = payload.get('contact_number')
    instagram_id = payload.get('instagram_id')
    video_url = payload.get('video_url')
    video_description = payload.get('video_description')
    avatar_url = normalize_avatar_url(payload.get('avatar_url'), user.get('username'))
    contact_sharing = payload.get('contact_sharing', False)
    allow_contact_after_payment = payload.get('allow_contact_after_payment', contact_sharing)
    email_notifications = payload.get('email_notifications', user.get('email_notifications', True))
    profile_visibility = payload.get('profile_visibility', user.get('profile_visibility', True))
    match_notifications = payload.get('match_notifications', user.get('match_notifications', True))
    skill_category_ids = payload.get('skill_category_ids') if 'skill_category_ids' in payload else None

    # Validate video_url
    validation_error = username_validation_error(username)
    if validation_error:
        return jsonify({'error': validation_error}), 400

    if video_url:
        import re
        youtube_regex = r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.be)\/.+$'
        gdrive_regex = r'^(https?\:\/\/)?(drive\.google\.com)\/.+$'
        if not re.match(youtube_regex, video_url) and not re.match(gdrive_regex, video_url):
            return jsonify({'error': 'Only YouTube or Google Drive links are allowed.'}), 400

    field_limits = {
        'full_name': (full_name, 120),
        'location': (location, 120),
        'skills_offered': (skills_offered, 600),
        'skills_wanted': (skills_wanted, 600),
        'bio': (bio, 1000),
        'phone': (phone, 40),
        'contact_number': (contact_number, 40),
        'instagram_id': (instagram_id, 120),
        'video_description': (video_description, 500),
    }
    for field_name, (field_value, max_length) in field_limits.items():
        if field_value and len(str(field_value)) > max_length:
            return jsonify({'error': f'{field_name.replace("_", " ").title()} is too long.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_user_public_profile_columns(cursor)
            ensure_engagement_schema(cursor)
            ensure_admin_schema(cursor)
            if not is_username_available(cursor, username, user['id']):
                return jsonify({'error': 'Username already taken.'}), 400
            cursor.execute(
                """
                UPDATE users SET 
                    username = %s, full_name = %s, location = %s, skills_offered = %s, skills_wanted = %s,
                    bio = %s, phone = %s, contact_number = %s, instagram_id = %s,
                    video_url = %s, video_description = %s, avatar_url = %s,
                    contact_sharing = %s, allow_contact_after_payment = %s,
                    email_notifications = %s, profile_visibility = %s, match_notifications = %s
                WHERE id = %s
                """,
                (
                    username, full_name, location, skills_offered, skills_wanted, bio, phone,
                    contact_number, instagram_id, video_url, video_description, avatar_url,
                    contact_sharing, allow_contact_after_payment, email_notifications,
                    profile_visibility, match_notifications, user['id']
                )
            )
            if skill_category_ids is not None:
                save_user_skill_categories(cursor, user['id'], skill_category_ids or [])
            if user.get('username') != username:
                log_admin_action(cursor, 'System', user['id'], 'username_change', username, f'Changed from @{user.get("username")}')
                create_admin_notification(
                    cursor,
                    'system',
                    'Username changed',
                    f'@{user.get("username")} changed username to @{username}.',
                    related_id=user['id'],
                    icon='fa-solid fa-user-pen'
                )
            conn.commit()
            session['username'] = username
            return jsonify({'success': True, 'avatar_url': avatar_url, 'username': username})
    except Exception as e:
        print(f"Error updating profile: {e}")
        return jsonify({'error': 'Unable to update profile'}), 500
    finally:
        conn.close()


@app.route('/api/user/settings', methods=['GET', 'POST'])
def user_settings_api():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Database error'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_user_settings_schema(cursor)
            if request.method == 'GET':
                cursor.execute(
                    """
                    SELECT contact_info_visibility, show_demo_video_publicly,
                           show_location_publicly, request_notifications,
                           chat_notifications, review_notifications,
                           payment_notifications, allow_matched_messages,
                           auto_scroll_messages
                    FROM user_settings
                    WHERE user_id = %s
                    """,
                    (user['id'],)
                )
                settings = default_user_settings()
                row = cursor.fetchone()
                if row:
                    settings.update(row)
                return jsonify({'success': True, 'settings': settings})

            payload = request.get_json(silent=True) or {}
            settings = clean_user_settings_payload(payload)
            cursor.execute(
                """
                INSERT INTO user_settings (
                    user_id, contact_info_visibility, show_demo_video_publicly,
                    show_location_publicly, request_notifications, chat_notifications,
                    review_notifications, payment_notifications, allow_matched_messages,
                    auto_scroll_messages
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    contact_info_visibility = VALUES(contact_info_visibility),
                    show_demo_video_publicly = VALUES(show_demo_video_publicly),
                    show_location_publicly = VALUES(show_location_publicly),
                    request_notifications = VALUES(request_notifications),
                    chat_notifications = VALUES(chat_notifications),
                    review_notifications = VALUES(review_notifications),
                    payment_notifications = VALUES(payment_notifications),
                    allow_matched_messages = VALUES(allow_matched_messages),
                    auto_scroll_messages = VALUES(auto_scroll_messages)
                """,
                (
                    user['id'],
                    settings['contact_info_visibility'],
                    settings['show_demo_video_publicly'],
                    settings['show_location_publicly'],
                    settings['request_notifications'],
                    settings['chat_notifications'],
                    settings['review_notifications'],
                    settings['payment_notifications'],
                    settings['allow_matched_messages'],
                    settings['auto_scroll_messages'],
                )
            )
            conn.commit()
            return jsonify({'success': True, 'settings': settings})
    except Exception as e:
        conn.rollback()
        print(f"Error saving user settings: {e}")
        return jsonify({'success': False, 'error': 'Unable to save settings'}), 500
    finally:
        conn.close()


@app.route('/api/account/change-password', methods=['POST'])
def change_password():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    current_password = payload.get('current_password')
    new_password = payload.get('new_password')

    if not current_password or not new_password:
        return jsonify({'error': 'Current and new password required'}), 400
    if len(new_password) < 8:
        return jsonify({'error': 'New password must be at least 8 characters'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT password_hash FROM users WHERE id = %s", (user['id'],))
            row = cursor.fetchone()
            if not row or not check_password_hash(row['password_hash'], current_password):
                return jsonify({'error': 'Incorrect current password'}), 400

            hashed_pw = generate_password_hash(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = %s, user_session_version = COALESCE(user_session_version, 1) + 1 WHERE id = %s",
                (hashed_pw, user['id'])
            )
            cursor.execute("SELECT COALESCE(user_session_version, 1) AS version FROM users WHERE id = %s", (user['id'],))
            version_row = cursor.fetchone() or {}
            conn.commit()
            session['user_session_version'] = int(version_row.get('version') or 1)
            return jsonify({'success': True})
    except Exception as e:
        print(f"Error changing password: {e}")
        return jsonify({'error': 'Unable to change password'}), 500
    finally:
        conn.close()


@app.route('/api/account/deactivate', methods=['POST'])
def deactivate_account():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    if user.get('is_admin'):
        return jsonify({'success': False, 'error': 'Admin accounts cannot be deactivated here'}), 403

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Database error'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_admin_schema(cursor)
            cursor.execute(
                """
                UPDATE users
                SET is_blocked = TRUE,
                    profile_visibility = FALSE,
                    user_session_version = COALESCE(user_session_version, 1) + 1
                WHERE id = %s AND COALESCE(is_admin, FALSE) = FALSE
                """,
                (user['id'],)
            )
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'error': 'Unable to deactivate this account'}), 400
            log_admin_action(cursor, 'System', user['id'], 'self_account_deactivate', user.get('username'), 'Blocked')
            create_admin_notification(
                cursor,
                'system',
                'User deactivated account',
                f'{user.get("username") or "A user"} deactivated their account.',
                related_id=user['id'],
                icon='fa-solid fa-user-lock'
            )
            conn.commit()
            clear_user_session_state()
            return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        print(f"Error deactivating account: {e}")
        return jsonify({'success': False, 'error': 'Unable to deactivate account'}), 500
    finally:
        conn.close()


@app.route('/api/account/delete', methods=['POST'])
def delete_account():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    if user.get('is_admin'):
        return jsonify({'error': 'Admin accounts cannot be deleted here'}), 403

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_admin_schema(cursor)
            cursor.execute(
                """
                UPDATE users
                SET is_deleted = TRUE,
                    is_blocked = TRUE,
                    deleted_at = NOW(),
                    deleted_by_user = TRUE,
                    profile_visibility = FALSE,
                    user_session_version = COALESCE(user_session_version, 1) + 1
                WHERE id = %s AND COALESCE(is_admin, FALSE) = FALSE
                """,
                (user['id'],)
            )
            if cursor.rowcount == 0:
                return jsonify({'error': 'Unable to delete this account'}), 400
            log_admin_action(cursor, 'System', user['id'], 'self_account_delete', user.get('username'), 'Deleted')
            create_admin_notification(
                cursor,
                'system',
                'User deleted account',
                f'{user.get("username") or "A user"} deleted their account.',
                related_id=user['id'],
                icon='fa-solid fa-user-slash'
            )
            conn.commit()
            clear_user_session_state()
            return jsonify({'success': True})
    except Exception as e:
        print(f"Error deleting account: {e}")
        return jsonify({'error': 'Unable to delete account'}), 500
    finally:
        conn.close()

@app.route('/api/search')
def search_api():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    q = request.args.get('q', '').strip()
    selected_filters = [
        item.strip().lower()
        for item in request.args.get('filters', '').split(',')
        if item.strip()
    ]

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        with conn.cursor() as cursor:
            ensure_unfollow_report_schema(cursor)
            user_columns = get_user_columns(cursor)
            optional_columns = [
                column for column in (
                    'bio', 'skill_type', 'level', 'skill_level', 'experience_level',
                    'proficiency_level', 'mode', 'learning_mode', 'availability_mode',
                    'meeting_preference', 'availability', 'available_time', 'schedule'
                )
                if column in user_columns
            ]
            select_optional = ''.join(f", {column}" for column in optional_columns)

            where_parts = [
                "id != %s",
                "COALESCE(is_deleted, FALSE) = FALSE",
                "COALESCE(is_blocked, FALSE) = FALSE",
                "COALESCE(is_admin, FALSE) = FALSE",
                "COALESCE(profile_visibility, TRUE) = TRUE"
            ]
            query_params = [user['id']]

            if q:
                search_pattern = f"%{q}%"
                searchable_columns = [
                    column for column in ('username', 'full_name', 'skills_offered', 'skills_wanted', 'bio')
                    if column in user_columns
                ]
                where_parts.append("(" + " OR ".join(f"{column} LIKE %s" for column in searchable_columns) + ")")
                query_params.extend([search_pattern] * len(searchable_columns))

            category_keywords = {
                'coding': ['code', 'coding', 'programming', 'python', 'java', 'javascript', 'web', 'html', 'css', 'react', 'node', 'sql', 'php', 'developer', 'development'],
                'design': ['design', 'ui', 'ux', 'figma', 'photoshop', 'illustrator', 'canva', 'graphics', 'graphic', 'prototype'],
                'marketing': ['marketing', 'seo', 'social media', 'content', 'branding', 'ads', 'advertising', 'sales', 'copywriting', 'growth'],
                'languages': ['language', 'english', 'spanish', 'french', 'german', 'hindi', 'urdu', 'arabic', 'japanese', 'korean', 'chinese']
            }

            def append_keyword_filter(keywords, columns):
                parts = []
                for column in columns:
                    if column not in user_columns:
                        continue
                    for keyword in keywords:
                        parts.append(f"{column} LIKE %s")
                        query_params.append(f"%{keyword}%")
                if parts:
                    where_parts.append("(" + " OR ".join(parts) + ")")

            for filter_name in selected_filters:
                if filter_name in category_keywords:
                    append_keyword_filter(category_keywords[filter_name], ['skills_offered', 'skills_wanted'])
                elif filter_name == 'skill-type':
                    where_parts.append("((skills_offered IS NOT NULL AND skills_offered != '') OR (skills_wanted IS NOT NULL AND skills_wanted != ''))")
                elif filter_name == 'level':
                    level_columns = [column for column in ('level', 'skill_level', 'experience_level', 'proficiency_level') if column in user_columns]
                    if level_columns:
                        append_keyword_filter(['beginner', 'intermediate', 'advanced', 'expert'], level_columns)
                elif filter_name == 'mode':
                    mode_columns = [column for column in ('mode', 'learning_mode', 'availability_mode', 'meeting_preference') if column in user_columns]
                    if mode_columns:
                        append_keyword_filter(['online', 'offline', 'remote', 'in-person', 'hybrid'], mode_columns)
                    else:
                        append_keyword_filter(['online', 'offline', 'remote', 'in-person', 'hybrid'], ['location', 'bio'])
                elif filter_name == 'availability':
                    availability_columns = [column for column in ('availability', 'available_time', 'schedule') if column in user_columns]
                    if availability_columns:
                        append_keyword_filter(['available', 'weekday', 'weekend', 'morning', 'evening', 'flexible'], availability_columns)
                    else:
                        append_keyword_filter(['available', 'weekday', 'weekend', 'morning', 'evening', 'flexible'], ['bio'])

            query = f"""
                SELECT id, username, full_name, location, avatar_url, skills_offered, skills_wanted, video_url{select_optional}
                FROM users
                WHERE {' AND '.join(where_parts)}
                ORDER BY
                    CASE
                        WHEN skills_offered LIKE %s THEN 1
                        WHEN skills_wanted LIKE %s THEN 2
                        WHEN username LIKE %s THEN 3
                        ELSE 4
                    END,
                    username ASC
                LIMIT 40
            """
            order_pattern = f"%{q}%" if q else "%"
            query_params.extend([order_pattern, order_pattern, order_pattern])
            cursor.execute(query, tuple(query_params))
            rows = cursor.fetchall()
            
            items = []
            for row in rows:
                relationship = get_relationship_state(cursor, user['id'], row['id'])
                match_details = enrich_skill_match(user, row)
                items.append({
                    'id': row['id'],
                    'name': row['full_name'] or row['username'],
                    'username': row['username'],
                    'location': row['location'] or 'Remote',
                    'avatar_url': normalize_avatar_url(row.get('avatar_url'), row.get('username')),
                    'skills': row['skills_offered'] or '',
                    'skills_offered': row['skills_offered'] or '',
                    'skills_wanted': row['skills_wanted'] or '',
                    'video_url': row['video_url'],
                    'relationship': relationship,
                    'match_percentage': match_details['match_percentage'],
                    'match_status': match_details['match_status'],
                    'match_badge_variant': match_details['match_badge_variant'],
                    'match_badge_label': match_details['match_badge_label'],
                    'categories': skill_categories_for_text(cursor, f"{row.get('skills_offered') or ''},{row.get('skills_wanted') or ''}")
                })
            return jsonify({'users': items})
    except Exception as e:
        print(f"Error searching: {e}")
        return jsonify({'error': 'Unable to search'}), 500
    finally:
        conn.close()


@app.route('/api/report', methods=['POST'])
def create_report():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or request.form.to_dict() or {}

    reported_user_id_raw = payload.get('reported_user_id') or payload.get('reported_id') or payload.get('user_id')
    reason = (payload.get('reason') or payload.get('type') or '').strip()
    description = (payload.get('description') or '').strip()

    if not reported_user_id_raw or reason not in ('Spam', 'Abuse', 'Fake', 'Other'):
        return jsonify({'error': 'Invalid report details'}), 400

    try:
        reported_user_id = int(reported_user_id_raw)
        reporter_user_id = int(user['id'])
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid report user'}), 400

    if reported_user_id == reporter_user_id:
        return jsonify({'error': 'You cannot report yourself'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    try:
        with conn.cursor() as cursor:
            ensure_admin_schema(cursor)
            cursor.execute("SELECT id, username FROM users WHERE id = %s", (reported_user_id,))
            reported_user = cursor.fetchone()
            if not reported_user:
                return jsonify({'error': 'Reported user not found'}), 404

            cursor.execute(
                """
                INSERT INTO reports
                    (reported_user_id, reported_by, reporter_user_id, reporter_username, reported_username, reason, description, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW())
                """,
                (
                    reported_user_id,
                    reporter_user_id,
                    reporter_user_id,
                    user.get('username'),
                    reported_user.get('username'),
                    reason,
                    description
                )
            )
            report_id = cursor.lastrowid
            conn.commit()
        return jsonify({'success': True, 'report_id': report_id})
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error submitting report: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Unable to submit report'}), 500
    finally:
        conn.close()


@app.route('/admin', methods=['GET', 'POST'])
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login_page():
    if get_current_admin():
        return redirect(url_for('admin_dashboard_page'))

    if request.method == 'POST':
        if is_rate_limited('admin_login', limit=8, window_seconds=600):
            flash('Too many login attempts. Please try again later.', 'error')
            return redirect(url_for('admin_login_page'))
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            flash('Invalid username or password', 'error')
            return redirect(url_for('admin_login_page'))

        conn = get_db_connection()
        if conn:
            try:
                with conn.cursor() as cursor:
                    ensure_admin_schema(cursor)
                    admin_account = get_admin_account(cursor, username=username)
                    config = get_admin_config(cursor)
                    conn.commit()
                if admin_account and check_password_hash(admin_account['password'], password):
                    start_admin_session(admin_account['username'], admin_id=0, full_name='Admin')
                    record_admin_activity(admin_name=admin_account['username'], action_type='admin_login', action_title='Admin login', action_description='Admin signed in.')
                    return redirect(url_for('admin_dashboard_page'))
                if username == config['admin_username'] and check_password_hash(config['admin_password_hash'], password):
                    start_admin_session(config['admin_username'], admin_id=0, full_name='Admin')
                    record_admin_activity(admin_name=config['admin_username'], action_type='admin_login', action_title='Admin login', action_description='Admin signed in.')
                    return redirect(url_for('admin_dashboard_page'))
            except Exception as e:
                print(f"Error checking admin login: {e}")
            finally:
                conn.close()

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            start_admin_session(ADMIN_USERNAME, admin_id=0, full_name='Admin')
            record_admin_activity(admin_name=ADMIN_USERNAME, action_type='admin_login', action_title='Admin login', action_description='Admin signed in.')
            return redirect(url_for('admin_dashboard_page'))
        flash('Invalid username or password', 'error')

    return render_template('admin/admin_login.html')


@app.route('/admin/forgot-password', methods=['GET', 'POST'])
def admin_forgot_password_page():
    reset_email = ADMIN_EMAIL
    show_reset_form = False

    if request.method == 'POST':
        action = request.form.get('action', 'request_code')
        email = request.form.get('email', '').strip().lower()

        if not email:
            flash('Admin email is required.', 'error')
            return redirect(url_for('admin_forgot_password_page'))

        conn = get_db_connection()
        if not conn:
            flash('Database connection failed.', 'error')
            return redirect(url_for('admin_forgot_password_page'))

        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                admin_account = get_admin_account(cursor, email=email)
                if not admin_account:
                    flash('No admin account found with this email.', 'error')
                    return render_template('admin/admin_forgot_password.html', reset_email=email, show_reset_form=False)

                if action == 'request_code':
                    reset_code = generate_admin_reset_code()
                    cursor.execute(
                        """
                        UPDATE admin_accounts
                        SET reset_code = %s, reset_code_expiry = DATE_ADD(NOW(), INTERVAL %s MINUTE)
                        WHERE id = %s
                        """,
                        (reset_code, OTP_EXPIRY_MINUTES, admin_account['id'])
                    )
                    conn.commit()

                    email_sent = send_admin_reset_email(admin_account['email'], reset_code)
                    if email_sent:
                        flash('Reset code sent to your email.', 'success')
                        return render_template(
                            'admin/admin_forgot_password.html',
                            reset_email=admin_account['email'],
                            show_reset_form=True
                        )

                    cursor.execute(
                        "UPDATE admin_accounts SET reset_code = NULL, reset_code_expiry = NULL WHERE id = %s",
                        (admin_account['id'],)
                    )
                    conn.commit()
                    flash('Unable to send reset code right now.', 'error')
                    return render_template(
                        'admin/admin_forgot_password.html',
                        reset_email=admin_account['email'],
                        show_reset_form=False
                    )

                reset_code = request.form.get('reset_code', '').strip()
                new_password = request.form.get('new_password', '')
                confirm_password = request.form.get('confirm_password', '')

                if not reset_code or not new_password or not confirm_password:
                    flash('All reset fields are required.', 'error')
                    return render_template('admin/admin_forgot_password.html', reset_email=email, show_reset_form=True)
                if new_password != confirm_password:
                    flash('New passwords do not match.', 'error')
                    return render_template('admin/admin_forgot_password.html', reset_email=email, show_reset_form=True)
                if len(new_password) < 8:
                    flash('New password must be at least 8 characters.', 'error')
                    return render_template('admin/admin_forgot_password.html', reset_email=email, show_reset_form=True)

                cursor.execute(
                    """
                    SELECT id, username, email, reset_code, reset_code_expiry
                    FROM admin_accounts
                    WHERE LOWER(email) = LOWER(%s)
                      AND reset_code = %s
                      AND reset_code_expiry IS NOT NULL
                    LIMIT 1
                    """,
                    (email, reset_code)
                )
                reset_row = cursor.fetchone()
                if not reset_row:
                    flash('Invalid reset code.', 'error')
                    return render_template('admin/admin_forgot_password.html', reset_email=email, show_reset_form=True)

                cursor.execute(
                    "SELECT reset_code_expiry < NOW() AS expired FROM admin_accounts WHERE id = %s",
                    (reset_row['id'],)
                )
                expiry_row = cursor.fetchone()
                if expiry_row and expiry_row.get('expired'):
                    flash('Reset code expired. Please request a new code.', 'error')
                    return render_template('admin/admin_forgot_password.html', reset_email=email, show_reset_form=False)

                new_password_hash = generate_password_hash(new_password)
                cursor.execute(
                    """
                    UPDATE admin_accounts
                    SET password = %s,
                        reset_code = NULL,
                        reset_code_expiry = NULL
                    WHERE id = %s
                    """,
                    (new_password_hash, reset_row['id'])
                )
                save_admin_setting(cursor, 'admin_username', reset_row['username'])
                save_admin_setting(cursor, 'admin_password_hash', new_password_hash)
                conn.commit()
            flash('Admin password reset successfully. Please login.', 'success')
            return redirect(url_for('admin_login_page'))
        except Exception as e:
            print(f"Error resetting admin password: {e}")
            traceback.print_exc()
            flash('Unable to reset admin password.', 'error')
        finally:
            conn.close()

    return render_template(
        'admin/admin_forgot_password.html',
        reset_email=reset_email,
        show_reset_form=show_reset_form
    )


@app.route('/admin/logout')
def admin_logout():
    admin_name = session.get('admin_username') or session.get('admin_name') or 'Admin'
    record_admin_activity(admin_name=admin_name, action_type='admin_logout', action_title='Admin logout', action_description='Admin signed out.')
    for key in ADMIN_SESSION_KEYS:
        session.pop(key, None)
    flash('Admin logged out.', 'success')
    return redirect(url_for('admin_login_page'))


@app.route('/admin/dashboard')
def admin_dashboard_page():
    admin, response = admin_required()
    if response:
        return response

    stats = {
        'users': 0,
        'requests': 0,
        'payments': 0,
        'revenue': 0,
        'active_users': 0,
        'deleted_accounts': 0,
        'fake_email_attempts': 0,
        'pending_requests': 0,
        'accepted_requests': 0,
        'rewards_claimed': 0,
    }
    recent_users = []
    recent_requests = []
    recent_transactions = []
    plans = []
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_days = [week_start + timedelta(days=day_offset) for day_offset in range(7)]
    month_start = now.replace(day=1)
    next_month = month_start.replace(year=month_start.year + 1, month=1) if month_start.month == 12 else month_start.replace(month=month_start.month + 1)
    month_days = [month_start + timedelta(days=day_offset) for day_offset in range((next_month - month_start).days)]
    chart_data = {
        'revenue_daily_labels': ['12 AM', '3 AM', '6 AM', '9 AM', '12 PM', '3 PM', '6 PM', '9 PM'],
        'revenue_daily': [0 for _ in range(8)],
        'revenue_weekly_labels': [day.strftime('%d %b') for day in week_days],
        'revenue_weekly': [0 for _ in week_days],
        'revenue_monthly_labels': [day.strftime('%d %b') for day in month_days],
        'revenue_monthly': [0 for _ in month_days],
        'months': ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
        'revenue_yearly': [0 for _ in range(12)],
        'user_pie_labels': ['Active Users', 'New Users', 'Deleted/Inactive'],
        'user_pie_values': [0, 0, 0],
    }

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                ensure_payment_schema(cursor)
                ensure_engagement_schema(cursor)
                conn.commit()
                cursor.execute("SELECT COUNT(*) AS count FROM users")
                stats['users'] = cursor.fetchone()['count']
                cursor.execute("SELECT COUNT(*) AS count FROM users WHERE COALESCE(is_blocked, FALSE) = FALSE AND COALESCE(is_deleted, FALSE) = FALSE")
                stats['active_users'] = cursor.fetchone()['count']
                cursor.execute("SELECT COUNT(*) AS count FROM users WHERE COALESCE(is_deleted, FALSE) = TRUE")
                stats['deleted_accounts'] = cursor.fetchone()['count']
                cursor.execute("SELECT COUNT(*) AS count FROM users WHERE YEAR(created_at) = YEAR(CURDATE()) AND MONTH(created_at) = MONTH(CURDATE())")
                new_users_this_month = cursor.fetchone()['count']
                chart_data['user_pie_values'] = [
                    stats['active_users'],
                    new_users_this_month,
                    stats['deleted_accounts'],
                ]
                cursor.execute("SELECT COUNT(*) AS count FROM disposable_email_attempts")
                stats['fake_email_attempts'] = cursor.fetchone()['count']
                cursor.execute("SELECT COUNT(*) AS count FROM requests")
                stats['requests'] = cursor.fetchone()['count']
                cursor.execute("SELECT COUNT(*) AS count FROM requests WHERE status = 'pending'")
                stats['pending_requests'] = cursor.fetchone()['count']
                cursor.execute("SELECT COUNT(*) AS count FROM requests WHERE status = 'accepted'")
                stats['accepted_requests'] = cursor.fetchone()['count']
                cursor.execute("SELECT COUNT(DISTINCT user_id) AS count FROM user_activity WHERE activity_type = 'daily_reward'")
                stats['rewards_claimed'] = cursor.fetchone()['count']
                if table_exists(cursor, 'payments'):
                    cursor.execute("SELECT COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total FROM payments WHERE status = 'successful'")
                    payment_stats = cursor.fetchone()
                    stats['payments'] = payment_stats['count']
                    stats['revenue'] = payment_stats['total']
                    cursor.execute(
                        """
                        SELECT FLOOR(HOUR(created_at) / 3) AS time_bucket, COALESCE(SUM(amount), 0) AS total
                        FROM payments
                        WHERE LOWER(status) = 'successful' AND DATE(created_at) = CURDATE()
                        GROUP BY FLOOR(HOUR(created_at) / 3)
                        ORDER BY time_bucket
                        """
                    )
                    for row in cursor.fetchall():
                        bucket_index = int(row['time_bucket'] or 0)
                        if 0 <= bucket_index < len(chart_data['revenue_daily']):
                            chart_data['revenue_daily'][bucket_index] = float(row['total'] or 0)
                    cursor.execute(
                        """
                        SELECT DATE(created_at) AS revenue_day, COALESCE(SUM(amount), 0) AS total
                        FROM payments
                        WHERE LOWER(status) = 'successful' AND YEARWEEK(created_at, 1) = YEARWEEK(CURDATE(), 1)
                        GROUP BY DATE(created_at)
                        ORDER BY revenue_day
                        """
                    )
                    weekly_totals = {row['revenue_day'].strftime('%Y-%m-%d') if hasattr(row['revenue_day'], 'strftime') else str(row['revenue_day']): float(row['total'] or 0) for row in cursor.fetchall()}
                    chart_data['revenue_weekly'] = [weekly_totals.get(day.strftime('%Y-%m-%d'), 0) for day in week_days]
                    cursor.execute(
                        """
                        SELECT DATE(created_at) AS revenue_day, COALESCE(SUM(amount), 0) AS total
                        FROM payments
                        WHERE LOWER(status) = 'successful' AND YEAR(created_at) = YEAR(CURDATE()) AND MONTH(created_at) = MONTH(CURDATE())
                        GROUP BY DATE(created_at)
                        ORDER BY revenue_day
                        """
                    )
                    monthly_totals = {row['revenue_day'].strftime('%Y-%m-%d') if hasattr(row['revenue_day'], 'strftime') else str(row['revenue_day']): float(row['total'] or 0) for row in cursor.fetchall()}
                    chart_data['revenue_monthly'] = [monthly_totals.get(day.strftime('%Y-%m-%d'), 0) for day in month_days]
                    cursor.execute(
                        """
                        SELECT MONTH(created_at) AS month_number, COALESCE(SUM(amount), 0) AS total
                        FROM payments
                        WHERE LOWER(status) = 'successful' AND YEAR(created_at) = YEAR(CURDATE())
                        GROUP BY MONTH(created_at)
                        ORDER BY month_number
                        """
                    )
                    for row in cursor.fetchall():
                        month_index = int(row['month_number']) - 1
                        if 0 <= month_index < 12:
                            chart_data['revenue_yearly'][month_index] = float(row['total'] or 0)
                    cursor.execute(
                        """
                        SELECT p.id, p.amount, p.status, p.created_at, u.username
                        FROM payments p
                        JOIN users u ON u.id = p.user_id
                        ORDER BY p.created_at DESC
                        LIMIT 5
                        """
                    )
                    recent_transactions = cursor.fetchall()

                cursor.execute(
                    "SELECT id, username, full_name, email, location, created_at FROM users ORDER BY created_at DESC LIMIT 5"
                )
                recent_users = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT r.id, r.status, r.payment_status, r.skill_requested, r.skill_offered, r.created_at,
                           sender.username AS sender_name, receiver.username AS receiver_name
                    FROM requests r
                    JOIN users sender ON sender.id = r.sender_id
                    JOIN users receiver ON receiver.id = r.receiver_id
                    ORDER BY r.created_at DESC
                    LIMIT 5
                    """
                )
                recent_requests = cursor.fetchall()
                cursor.execute("SELECT * FROM platform_plans ORDER BY id")
                plans = cursor.fetchall()
        except Exception as e:
            print(f"Error loading admin dashboard: {e}")
        finally:
            conn.close()

    return render_template(
        'admin/admin_dashboard.html',
        admin=admin,
        stats=stats,
        recent_users=recent_users,
        recent_requests=recent_requests,
        recent_transactions=recent_transactions,
        plans=plans,
        chart_data=chart_data,
        active_page='dashboard'
    )


@app.route('/admin/users')
def manage_users_page():
    admin, response = admin_required()
    if response:
        return response

    users = []
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                ensure_user_public_profile_columns(cursor)
                ensure_premium_schema(cursor)
                conn.commit()
                cursor.execute(
                    """
                    SELECT id, username, full_name, email, location, avatar_url, skills_offered,
                           skills_wanted, is_admin, is_blocked,
                           COALESCE(is_premium, FALSE) AS is_premium,
                           premium_expiry_date,
                           COALESCE(email_notifications, TRUE) AS email_notifications,
                           COALESCE(match_notifications, TRUE) AS match_notifications,
                           COALESCE(profile_visibility, TRUE) AS profile_visibility,
                           COALESCE(is_verified, TRUE) AS is_verified,
                           COALESCE(is_deleted, FALSE) AS is_deleted,
                           block_reason, delete_reason, deleted_at, created_at,
                           (
                               SELECT aa.action_type
                               FROM admin_actions aa
                               WHERE aa.user_id = users.id
                               ORDER BY aa.created_at DESC, aa.id DESC
                               LIMIT 1
                           ) AS latest_action_type,
                           (
                               SELECT aa.account_status
                               FROM admin_actions aa
                               WHERE aa.user_id = users.id
                               ORDER BY aa.created_at DESC, aa.id DESC
                               LIMIT 1
                           ) AS latest_account_status
                    FROM users
                    WHERE COALESCE(is_deleted, FALSE) = FALSE
                    ORDER BY created_at DESC
                    """
                )
                users = cursor.fetchall()
                for item in users:
                    item['avatar_url'] = normalize_avatar_url(item.get('avatar_url'), item.get('username'))
        except Exception as e:
            print(f"Error loading users: {e}")
        finally:
            conn.close()

    return render_template('admin/manage_users.html', admin=admin, users=users, active_page='users')


@app.route('/admin/users/<int:user_id>/<action>', methods=['POST'])
def admin_user_action(user_id, action):
    admin, response = admin_required()
    if response:
        return response
    if user_id == admin['id']:
        flash('You cannot modify your own admin account.', 'error')
        return redirect(url_for('manage_users_page'))

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                reason = (request.form.get('moderation_reason') or '').strip()
                if action in ('block', 'delete') and not reason:
                    flash('Reason is required for block/delete actions.', 'error')
                    return redirect(url_for('manage_users_page'))
                if action == 'block':
                    cursor.execute("UPDATE users SET is_blocked = TRUE, block_reason = %s WHERE id = %s AND is_admin = FALSE", (reason, user_id))
                    log_admin_action(cursor, admin['username'], user_id, 'block', account_status='Blocked', action_reason=reason)
                    create_user_notification(cursor, user_id, 'account_action', 'Account action taken', f'Your account was blocked. Reason: {reason}', user_id)
                    create_admin_notification(cursor, 'system', 'Admin alert', f'{admin["username"]} blocked user #{user_id}.', related_id=user_id, icon='fa-solid fa-user-lock')
                elif action == 'unblock':
                    cursor.execute("UPDATE users SET is_blocked = FALSE, block_reason = NULL WHERE id = %s AND is_admin = FALSE", (user_id,))
                    log_admin_action(cursor, admin['username'], user_id, 'unblock', account_status='Active')
                    create_admin_notification(cursor, 'system', 'Admin alert', f'{admin["username"]} unblocked user #{user_id}.', related_id=user_id, icon='fa-solid fa-user-check')
                elif action == 'delete':
                    cursor.execute(
                        """
                        UPDATE users
                        SET is_deleted = TRUE,
                            is_blocked = TRUE,
                            deleted_at = NOW(),
                            deleted_by_user = FALSE,
                            delete_reason = %s,
                            profile_visibility = FALSE
                        WHERE id = %s AND is_admin = FALSE
                        """,
                        (reason, user_id)
                    )
                    log_admin_action(cursor, admin['username'], user_id, 'delete', account_status='Deleted', action_reason=reason)
                    create_user_notification(cursor, user_id, 'account_action', 'Account action taken', f'Your account was deleted. Reason: {reason}', user_id)
                    create_admin_notification(cursor, 'system', 'Admin alert', f'{admin["username"]} deleted user #{user_id}.', related_id=user_id, icon='fa-solid fa-trash')
                elif action == 'verify-email':
                    cursor.execute(
                        """
                        UPDATE users
                        SET is_verified = TRUE,
                            verification_otp = NULL,
                            verification_token = NULL,
                            verification_expiry = NULL
                        WHERE id = %s AND is_admin = FALSE
                        """,
                        (user_id,)
                    )
                    log_admin_action(cursor, admin['username'], user_id, 'manual_email_verify', account_status='Verified')
                    create_admin_notification(cursor, 'system', 'Admin alert', f'{admin["username"]} manually verified user #{user_id}.', related_id=user_id, icon='fa-solid fa-envelope-circle-check')
                conn.commit()
        finally:
            conn.close()
    return redirect(url_for('manage_users_page'))


@app.route('/admin/email-security')
def admin_email_security_page():
    admin, response = admin_required()
    if response:
        return response

    attempts = []
    stats = {'attempts': 0, 'domains': 0}
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                conn.commit()
                cursor.execute("SELECT COUNT(*) AS count FROM disposable_email_attempts")
                stats['attempts'] = cursor.fetchone()['count']
                cursor.execute("SELECT COUNT(DISTINCT domain) AS count FROM disposable_email_attempts")
                stats['domains'] = cursor.fetchone()['count']
                cursor.execute(
                    """
                    SELECT id, email, domain, source, ip_address, user_agent, created_at
                    FROM disposable_email_attempts
                    ORDER BY created_at DESC
                    LIMIT 200
                    """
                )
                attempts = cursor.fetchall()
        except Exception as e:
            print(f"Error loading email security page: {e}")
        finally:
            conn.close()

    return render_template(
        'admin/email_security.html',
        admin=admin,
        attempts=attempts,
        stats=stats,
        active_page='email_security'
    )


@app.route('/admin/deleted-users')
def admin_deleted_users_page():
    admin, response = admin_required()
    if response:
        return response

    deleted_users = []
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                conn.commit()
                cursor.execute(
                    """
                    SELECT id, username, full_name, email, location, avatar_url,
                           skills_offered, skills_wanted, deleted_at, created_at,
                           delete_reason,
                           COALESCE(deleted_by_user, FALSE) AS deleted_by_user,
                           (
                               SELECT aa.admin_name
                               FROM admin_actions aa
                               WHERE aa.user_id = users.id
                                 AND aa.action_type IN ('self_account_delete', 'delete')
                               ORDER BY aa.created_at DESC, aa.id DESC
                               LIMIT 1
                           ) AS deleted_by,
                           (
                               SELECT aa.action_reason
                               FROM admin_actions aa
                               WHERE aa.user_id = users.id
                                 AND aa.action_type IN ('self_account_delete', 'delete')
                               ORDER BY aa.created_at DESC, aa.id DESC
                               LIMIT 1
                           ) AS action_reason,
                           (
                               SELECT aa.created_at
                               FROM admin_actions aa
                               WHERE aa.user_id = users.id
                                 AND aa.action_type IN ('self_account_delete', 'delete')
                               ORDER BY aa.created_at DESC, aa.id DESC
                               LIMIT 1
                           ) AS action_at
                    FROM users
                    WHERE COALESCE(is_deleted, FALSE) = TRUE
                    ORDER BY deleted_at DESC, id DESC
                    """
                )
                deleted_users = cursor.fetchall()
                for deleted_user in deleted_users:
                    deleted_user['avatar_url'] = normalize_avatar_url(
                        deleted_user.get('avatar_url'),
                        deleted_user.get('username')
                    )
        except Exception as e:
            print(f"Error loading deleted users: {e}")
        finally:
            conn.close()

    return render_template(
        'admin/deleted_users.html',
        admin=admin,
        deleted_users=deleted_users,
        active_page='deleted_users'
    )


@app.route('/admin/deleted-users/<int:user_id>/restore', methods=['POST'])
def admin_restore_deleted_user(user_id):
    admin, response = admin_required()
    if response:
        return response

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                cursor.execute(
                    """
                    UPDATE users
                    SET is_deleted = FALSE,
                        is_blocked = FALSE,
                        deleted_at = NULL,
                        deleted_by_user = FALSE,
                        profile_visibility = TRUE
                    WHERE id = %s AND COALESCE(is_admin, FALSE) = FALSE
                    """,
                    (user_id,)
                )
                if cursor.rowcount:
                    log_admin_action(cursor, admin['username'], user_id, 'restore', account_status='Active')
                    create_admin_notification(cursor, 'system', 'Admin alert', f'{admin["username"]} restored user #{user_id}.', related_id=user_id, icon='fa-solid fa-user-check')
                    flash('User account restored.', 'success')
                else:
                    flash('Unable to restore this account.', 'error')
                conn.commit()
        finally:
            conn.close()
    return redirect(url_for('admin_deleted_users_page'))


@app.route('/admin/requests')
def manage_requests_page():
    admin, response = admin_required()
    if response:
        return response

    requests_list = []
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT r.id, r.skill_requested, r.skill_offered, r.status,
                           r.payment_status, r.payment_date, r.expiry_date, r.created_at,
                           sender.username AS sender_name,
                           receiver.username AS receiver_name,
                           sender.skills_offered AS sender_teaches,
                           sender.skills_wanted AS sender_learns,
                           receiver.skills_offered AS receiver_teaches,
                           receiver.skills_wanted AS receiver_learns
                    FROM requests r
                    JOIN users sender ON sender.id = r.sender_id
                    JOIN users receiver ON receiver.id = r.receiver_id
                    ORDER BY r.created_at DESC
                    """
                )
                requests_list = cursor.fetchall()
        except Exception as e:
            print(f"Error loading requests: {e}")
        finally:
            conn.close()

    return render_template(
        'admin/manage_requests.html',
        admin=admin,
        requests_list=requests_list,
        active_page='requests'
    )


@app.route('/admin/requests/<int:request_id>/<action>', methods=['POST'])
def admin_request_action(request_id, action):
    admin, response = admin_required()
    if response:
        return response
    if action not in ('accepted', 'rejected'):
        return redirect(url_for('manage_requests_page'))

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE requests SET status = %s WHERE id = %s", (action, request_id))
                create_admin_notification(
                    cursor,
                    'request',
                    f'Request {action}',
                    f'{admin["username"]} marked request #{request_id} as {action}.',
                    related_id=request_id,
                    icon='fa-solid fa-clipboard-check'
                )
                record_admin_activity(cursor, admin=admin, action_type='request_updated', action_title='Request updated', action_description=f'Request #{request_id} marked as {action}.', target_type='request', target_id=request_id)
                conn.commit()
        finally:
            conn.close()
    return redirect(url_for('manage_requests_page'))


@app.route('/admin/unfollow-reports')
def admin_unfollow_reports_page():
    admin, response = admin_required()
    if response:
        return response

    reports = []
    reason_counts = []
    total_reports = 0
    page = max(1, request.args.get('page', default=1, type=int) or 1)
    per_page = 12
    selected_action = (request.args.get('action') or '').strip()
    where_sql = ''
    params = []
    if selected_action in ('unfollow', 'remove_match', 'cancel_request'):
        where_sql = 'WHERE ur.action_type = %s'
        params.append(selected_action)
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS count
                    FROM unfollow_reports ur
                    {where_sql}
                    """,
                    params
                )
                total_reports = cursor.fetchone()['count']
                cursor.execute(
                    f"""
                    SELECT ur.id, ur.match_id, ur.request_id, ur.action_type,
                           ur.previous_request_status, ur.reason, ur.custom_reason,
                           ur.status, ur.created_at,
                           unfollower.username AS unfollower_username,
                           unfollower.full_name AS unfollower_name,
                           unfollowed.username AS unfollowed_username,
                           unfollowed.full_name AS unfollowed_name
                    FROM unfollow_reports ur
                    JOIN users unfollower ON unfollower.id = ur.unfollower_id
                    JOIN users unfollowed ON unfollowed.id = ur.unfollowed_user_id
                    {where_sql}
                    ORDER BY ur.created_at DESC
                    LIMIT %s OFFSET %s
                    """
                    ,
                    params + [per_page, (page - 1) * per_page]
                )
                reports = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT reason, COUNT(*) AS count
                    FROM unfollow_reports
                    GROUP BY reason
                    ORDER BY count DESC, reason ASC
                    """
                )
                reason_counts = cursor.fetchall()
        except Exception as e:
            print(f"Error loading unfollow reports: {e}")
        finally:
            conn.close()

    return render_template(
        'admin/unfollow_reports.html',
        admin=admin,
        reports=reports,
        reason_counts=reason_counts,
        selected_action=selected_action,
        page=page,
        per_page=per_page,
        total_reports=total_reports,
        total_pages=max(1, (total_reports + per_page - 1) // per_page),
        active_page='unfollow_reports'
    )


@app.route('/admin/skills')
def admin_skills_page():
    admin, response = admin_required()
    if response:
        return response

    skills = []
    categories = []
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_engagement_schema(cursor)
                cursor.execute(
                    """
                    SELECT u.id, u.username, u.full_name, u.email, u.skills_offered AS teach_skill,
                           u.skills_wanted AS learn_skill, u.created_at,
                           GROUP_CONCAT(sc.category_name ORDER BY sc.category_name SEPARATOR ', ') AS categories
                    FROM users u
                    LEFT JOIN user_skill_categories usc ON usc.user_id = u.id
                    LEFT JOIN skill_categories sc ON sc.id = usc.category_id
                    WHERE (u.skills_offered IS NOT NULL AND u.skills_offered != '')
                       OR (u.skills_wanted IS NOT NULL AND u.skills_wanted != '')
                       OR usc.category_id IS NOT NULL
                    GROUP BY u.id, u.username, u.full_name, u.email, u.skills_offered, u.skills_wanted, u.created_at
                    ORDER BY u.created_at DESC
                    """
                )
                skills = cursor.fetchall()
                categories = get_all_skill_categories(cursor)
        except Exception as e:
            print(f"Error loading admin skills: {e}")
        finally:
            conn.close()
    return render_template('admin/manage_skills.html', admin=admin, skills=skills, categories=categories, active_page='skills')


@app.route('/admin/skill-categories/save', methods=['POST'])
def admin_save_skill_category():
    admin, response = admin_required()
    if response:
        return response

    category_id = request.form.get('category_id', type=int)
    category_name = (request.form.get('category_name') or '').strip()
    icon = (request.form.get('icon') or 'fa-solid fa-layer-group').strip()
    keywords = (request.form.get('keywords') or '').strip()
    if not category_name:
        flash('Category name is required.', 'error')
        return redirect(url_for('admin_skills_page'))

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_engagement_schema(cursor)
                if category_id:
                    cursor.execute(
                        "UPDATE skill_categories SET category_name = %s, icon = %s, keywords = %s WHERE id = %s",
                        (category_name, icon, keywords, category_id)
                    )
                    action_text = 'updated'
                else:
                    cursor.execute(
                        """
                        INSERT INTO skill_categories (category_name, icon, keywords)
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE icon = VALUES(icon), keywords = VALUES(keywords)
                        """,
                        (category_name, icon, keywords)
                    )
                    action_text = 'saved'
                create_admin_notification(
                    cursor,
                    'system',
                    'Skill category updated',
                    f'{admin["username"]} {action_text} skill category "{category_name}".',
                    related_id=category_id,
                    icon='fa-solid fa-layer-group'
                )
                record_admin_activity(cursor, admin=admin, action_type='skill_category_save', action_title='Skill category saved', action_description=f'Skill category "{category_name}" {action_text}.', target_type='skill_category', target_id=category_id, target_name=category_name)
                conn.commit()
                flash('Skill category saved.', 'success')
        except Exception as e:
            print(f"Error saving skill category: {e}")
            flash('Unable to save skill category.', 'error')
        finally:
            conn.close()
    return redirect(url_for('admin_skills_page'))


@app.route('/admin/skill-categories/<int:category_id>/delete', methods=['POST'])
def admin_delete_skill_category(category_id):
    admin, response = admin_required()
    if response:
        return response

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_engagement_schema(cursor)
                cursor.execute("SELECT category_name FROM skill_categories WHERE id = %s", (category_id,))
                row = cursor.fetchone() or {}
                cursor.execute("DELETE FROM user_skill_categories WHERE category_id = %s", (category_id,))
                cursor.execute("DELETE FROM skill_categories WHERE id = %s", (category_id,))
                create_admin_notification(
                    cursor,
                    'system',
                    'Skill category deleted',
                    f'{admin["username"]} deleted skill category "{row.get("category_name") or category_id}".',
                    related_id=category_id,
                    icon='fa-solid fa-trash'
                )
                record_admin_activity(cursor, admin=admin, action_type='skill_category_delete', action_title='Skill category deleted', action_description=f'Skill category "{row.get("category_name") or category_id}" deleted.', target_type='skill_category', target_id=category_id, target_name=row.get('category_name'))
                conn.commit()
                flash('Skill category deleted.', 'success')
        except Exception as e:
            print(f"Error deleting skill category: {e}")
            flash('Unable to delete skill category.', 'error')
        finally:
            conn.close()
    return redirect(url_for('admin_skills_page'))


@app.route('/admin/daily-activity')
def admin_daily_activity_page():
    admin, response = admin_required()
    if response:
        return response

    activity = []
    leaders = []
    stats = {'total_xp': 0, 'rewards': 0, 'active_streaks': 0, 'broken_streaks': 0}
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_engagement_schema(cursor)
                ensure_chat_attachment_schema(cursor)
                ensure_unfollow_report_schema(cursor)
                cursor.execute("SELECT COALESCE(SUM(xp_points), 0) AS total FROM users")
                stats['total_xp'] = cursor.fetchone()['total']
                cursor.execute("SELECT COUNT(*) AS count FROM user_activity WHERE activity_type = 'daily_reward'")
                stats['rewards'] = cursor.fetchone()['count']
                cursor.execute(
                    f"""
                    SELECT r.id AS request_id, r.skill_requested, r.skill_offered, r.payment_status,
                           sender.id AS user_id, sender.username, sender.full_name, sender.last_reward_claimed_at,
                           receiver.id AS partner_id, receiver.username AS partner_username, receiver.full_name AS partner_full_name,
                           (SELECT MAX(m.created_at) FROM messages m WHERE m.request_id = r.id) AS last_interaction_at,
                           (SELECT COUNT(*) FROM messages m WHERE m.request_id = r.id) AS message_count,
                           (SELECT COUNT(*) FROM messages m WHERE m.request_id = r.id AND m.attachment_path IS NOT NULL) AS shared_files
                    FROM requests r
                    JOIN users sender ON sender.id = r.sender_id
                    JOIN users receiver ON receiver.id = r.receiver_id
                    WHERE r.status = 'accepted'
                      AND {active_relationship_filter_sql('r')}
                      AND COALESCE(sender.is_deleted, FALSE) = FALSE
                      AND COALESCE(receiver.is_deleted, FALSE) = FALSE
                    ORDER BY last_interaction_at DESC, r.created_at DESC
                    LIMIT 200
                    """
                )
                leaders = cursor.fetchall()
                now = datetime.now()
                for row in leaders:
                    current_streak, best_streak = calculate_shared_message_streak(cursor, row['request_id'], row['user_id'], row['partner_id'])
                    row['current_streak'] = current_streak
                    row['longest_streak'] = best_streak
                    row['xp_points'] = int(row.get('message_count') or 0) * 2 + int(row.get('shared_files') or 0) * 5
                    last_interaction = row.get('last_interaction_at')
                    if current_streak > 0:
                        row['activity_status'] = 'active'
                    elif isinstance(last_interaction, datetime) and now - last_interaction <= timedelta(hours=72):
                        row['activity_status'] = 'pending'
                    else:
                        row['activity_status'] = 'broken'
                stats['active_streaks'] = sum(1 for row in leaders if row.get('activity_status') == 'active')
                stats['broken_streaks'] = sum(1 for row in leaders if row.get('activity_status') == 'broken')
                cursor.execute(
                    """
                    SELECT ua.id, ua.activity_type, ua.title, ua.points, ua.related_id, ua.created_at,
                           u.username, u.full_name
                    FROM user_activity ua
                    JOIN users u ON u.id = ua.user_id
                    WHERE ua.activity_type IN ('request_accepted', 'chat_message', 'review_given', 'daily_reward', 'premium_unlock')
                    ORDER BY ua.created_at DESC
                    LIMIT 200
                    """
                )
                activity = cursor.fetchall()
        except Exception as e:
            print(f"Error loading admin daily activity: {e}")
        finally:
            conn.close()

    return render_template(
        'admin/daily_activity.html',
        admin=admin,
        stats=stats,
        leaders=leaders,
        activity=activity,
        active_page='daily_activity'
    )


@app.route('/admin/chats')
def admin_chats_page():
    admin, response = admin_required()
    if response:
        return response

    chats = []
    selected_chat = None
    active_filter = request.args.get('filter', 'all').lower()
    selected_key = request.args.get('conversation', '').strip()
    if active_filter not in ('all', 'active', 'locked', 'deleted', 'recent'):
        active_filter = 'all'

    def build_conversation_key(message):
        if message.get('request_id'):
            return f"req-{message['request_id']}"
        first_id = min(message.get('sender_id') or 0, message.get('receiver_id') or 0)
        second_id = max(message.get('sender_id') or 0, message.get('receiver_id') or 0)
        return f"pair-{first_id}-{second_id}"

    def build_chat_status(message):
        if message.get('sender_deleted') or message.get('receiver_deleted'):
            return 'deleted'
        if message.get('payment_status') == 'paid':
            return 'active'
        return 'locked'

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                conn.commit()
                if table_exists(cursor, 'messages'):
                    cursor.execute(
                        """
                        SELECT m.id, m.request_id, m.sender_id, m.receiver_id,
                               COALESCE(m.message_text, m.content) AS message_text,
                               m.created_at,
                               sender.username AS sender_username,
                               sender.full_name AS sender_full_name,
                               sender.avatar_url AS sender_avatar_url,
                               COALESCE(sender.is_deleted, FALSE) AS sender_deleted,
                               receiver.username AS receiver_username,
                               receiver.full_name AS receiver_full_name,
                               receiver.avatar_url AS receiver_avatar_url,
                               COALESCE(receiver.is_deleted, FALSE) AS receiver_deleted,
                               COALESCE(r.payment_status, 'pending') AS payment_status
                        FROM messages m
                        JOIN users sender ON sender.id = m.sender_id
                        JOIN users receiver ON receiver.id = m.receiver_id
                        LEFT JOIN requests r ON r.id = m.request_id
                        ORDER BY m.created_at DESC
                        LIMIT 500
                        """
                    )
                    messages = cursor.fetchall()
                    grouped_chats = {}
                    for message in messages:
                        conversation_key = build_conversation_key(message)
                        status = build_chat_status(message)
                        if conversation_key not in grouped_chats:
                            grouped_chats[conversation_key] = {
                                'conversation_key': conversation_key,
                                'request_id': message.get('request_id'),
                                'user_a_id': message.get('sender_id'),
                                'user_a': message.get('sender_username'),
                                'user_a_name': message.get('sender_full_name') or message.get('sender_username'),
                                'user_a_avatar': normalize_avatar_url(message.get('sender_avatar_url'), message.get('sender_username')),
                                'user_b_id': message.get('receiver_id'),
                                'user_b': message.get('receiver_username'),
                                'user_b_name': message.get('receiver_full_name') or message.get('receiver_username'),
                                'user_b_avatar': normalize_avatar_url(message.get('receiver_avatar_url'), message.get('receiver_username')),
                                'last_message': message.get('message_text'),
                                'last_message_at': message.get('created_at'),
                                'chat_status': status,
                                'message_count': 0,
                                'messages': []
                            }
                        chat = grouped_chats[conversation_key]
                        chat['message_count'] += 1
                        chat['messages'].append({
                            'id': message.get('id'),
                            'sender_id': message.get('sender_id'),
                            'sender_name': message.get('sender_full_name') or message.get('sender_username'),
                            'message_text': message.get('message_text') or 'No message content',
                            'created_at': message.get('created_at'),
                            'is_user_a': message.get('sender_id') == chat['user_a_id']
                        })

                    chats = list(grouped_chats.values())
                    for chat in chats:
                        chat['messages'] = list(reversed(chat['messages']))

                    if active_filter == 'recent':
                        chats = chats[:20]
                    elif active_filter != 'all':
                        chats = [chat for chat in chats if chat['chat_status'] == active_filter]

                    if selected_key:
                        selected_chat = next(
                            (chat for chat in chats if chat['conversation_key'] == selected_key),
                            None
                        )
                        if selected_chat:
                            if selected_chat.get('request_id'):
                                cursor.execute(
                                    """
                                    SELECT m.id, m.sender_id,
                                           COALESCE(m.message_text, m.content) AS message_text,
                                           m.created_at,
                                           sender.username AS sender_username,
                                           sender.full_name AS sender_full_name
                                    FROM messages m
                                    JOIN users sender ON sender.id = m.sender_id
                                    WHERE m.request_id = %s
                                    ORDER BY m.created_at ASC
                                    """,
                                    (selected_chat['request_id'],)
                                )
                            else:
                                cursor.execute(
                                    """
                                    SELECT m.id, m.sender_id,
                                           COALESCE(m.message_text, m.content) AS message_text,
                                           m.created_at,
                                           sender.username AS sender_username,
                                           sender.full_name AS sender_full_name
                                    FROM messages m
                                    JOIN users sender ON sender.id = m.sender_id
                                    WHERE m.request_id IS NULL
                                      AND ((m.sender_id = %s AND m.receiver_id = %s)
                                        OR (m.sender_id = %s AND m.receiver_id = %s))
                                    ORDER BY m.created_at ASC
                                    """,
                                    (
                                        selected_chat['user_a_id'],
                                        selected_chat['user_b_id'],
                                        selected_chat['user_b_id'],
                                        selected_chat['user_a_id']
                                    )
                                )
                            selected_chat['messages'] = [
                                {
                                    'id': message.get('id'),
                                    'sender_id': message.get('sender_id'),
                                    'sender_name': message.get('sender_full_name') or message.get('sender_username'),
                                    'message_text': message.get('message_text') or 'No message content',
                                    'created_at': message.get('created_at'),
                                    'is_user_a': message.get('sender_id') == selected_chat['user_a_id']
                                }
                                for message in cursor.fetchall()
                            ]
        except Exception as e:
            print(f"Error loading admin chats: {e}")
        finally:
            conn.close()
    return render_template(
        'admin/manage_chats.html',
        admin=admin,
        chats=chats,
        selected_chat=selected_chat,
        active_filter=active_filter,
        active_page='chats'
    )


@app.route('/admin/disputes')
def admin_disputes_page():
    admin, response = admin_required()
    if response:
        return response

    disputes = []
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                conn.commit()
                cursor.execute(
                    """
                    SELECT r.id, r.reason, r.description,
                           COALESCE(NULLIF(r.status, ''), 'pending') AS status,
                           r.created_at,
                           COALESCE(r.reporter_username, reporter.username, CONCAT('User #', COALESCE(r.reported_by, r.reporter_user_id))) AS reporter_name,
                           COALESCE(r.reported_username, reported.username, CONCAT('User #', r.reported_user_id)) AS reported_name
                    FROM reports r
                    LEFT JOIN users reporter ON reporter.id = COALESCE(r.reported_by, r.reporter_user_id)
                    LEFT JOIN users reported ON reported.id = r.reported_user_id
                    ORDER BY r.created_at DESC
                    """
                )
                disputes = cursor.fetchall()
                for dispute in disputes:
                    dispute['status'] = normalize_dispute_status(dispute.get('status'))
                    dispute['status_label'] = DISPUTE_STATUS_LABELS[dispute['status']]
        except Exception as e:
            print(f"Error loading admin disputes: {e}")
        finally:
            conn.close()
    return render_template('admin/manage_disputes.html', admin=admin, disputes=disputes, active_page='disputes')


@app.route('/admin/disputes/<int:dispute_id>/status/<status>', methods=['POST'])
def admin_update_dispute_status(dispute_id, status):
    admin, response = admin_required()
    if response:
        return response

    normalized_status = normalize_dispute_status(status)
    if normalized_status not in DISPUTE_STATUS_LABELS:
        flash('Invalid dispute status.', 'error')
        return redirect(url_for('admin_disputes_page'))

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                cursor.execute("UPDATE reports SET status = %s WHERE id = %s", (normalized_status, dispute_id))
                if cursor.rowcount:
                    create_admin_notification(
                        cursor,
                        'system',
                        'Dispute status updated',
                        f'{admin["username"]} marked dispute #{dispute_id} as {DISPUTE_STATUS_LABELS[normalized_status]}.',
                        related_id=dispute_id,
                        icon='fa-solid fa-triangle-exclamation'
                    )
                    record_admin_activity(cursor, admin=admin, action_type='dispute_updated', action_title='Dispute updated', action_description=f'Dispute #{dispute_id} marked as {DISPUTE_STATUS_LABELS[normalized_status]}.', target_type='dispute', target_id=dispute_id)
                    flash(f'Dispute marked as {DISPUTE_STATUS_LABELS[normalized_status]}.', 'success')
                else:
                    flash('Dispute not found.', 'error')
                conn.commit()
        except Exception as e:
            print(f"Error updating dispute status: {e}")
            flash('Unable to update dispute status.', 'error')
        finally:
            conn.close()
    else:
        flash('Database connection failed.', 'error')
    return redirect(url_for('admin_disputes_page'))


@app.route('/admin/payments')
def manage_payments_page():
    admin, response = admin_required()
    if response:
        return response

    payments = []
    analytics = {'total': 0, 'successful': 0, 'pending': 0, 'failed': 0, 'active_subscriptions': 0}
    reminder_settings = {'enabled': True, 'before_7': True, 'before_3': True, 'before_1': True, 'expired': True, 'last_run': ''}
    reminder_users = []
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                ensure_payment_schema(cursor)
                ensure_subscription_reminder_schema(cursor)
                reminder_settings = get_subscription_reminder_settings(cursor)
                conn.commit()
                if table_exists(cursor, 'payments'):
                    cursor.execute(
                        """
                        SELECT p.id, p.merchant_order_id, p.transaction_id, p.amount,
                               p.status, p.payment_status, p.gateway, p.created_at,
                               u.username, u.email, p.request_id,
                               CASE
                                   WHEN p.status = 'successful' THEN 'unlocked'
                                   WHEN p.status IN ('created', 'pending') THEN 'pending'
                                   ELSE 'locked'
                               END AS chat_unlock_status
                        FROM payments p
                        JOIN users u ON u.id = p.user_id
                        ORDER BY p.created_at DESC
                        """
                    )
                    payments = cursor.fetchall()
                    analytics['total'] = len(payments)
                    analytics['successful'] = sum(1 for item in payments if item.get('status') == 'successful')
                    analytics['pending'] = sum(1 for item in payments if item.get('status') in ('created', 'pending'))
                    analytics['failed'] = sum(1 for item in payments if item.get('status') == 'failed')
                    analytics['active_subscriptions'] = analytics['successful']
                cursor.execute(
                    """
                    SELECT u.id, u.username, u.full_name, u.avatar_url, u.premium_expiry_date,
                           DATEDIFF(DATE(u.premium_expiry_date), CURDATE()) AS remaining_days,
                           MAX(l.sent_at) AS last_reminder_at,
                           SUBSTRING_INDEX(GROUP_CONCAT(l.reminder_key ORDER BY l.sent_at DESC), ',', 1) AS last_reminder_key
                    FROM users u
                    LEFT JOIN subscription_reminder_logs l
                      ON l.user_id = u.id
                     AND l.expiry_date = DATE(u.premium_expiry_date)
                    WHERE COALESCE(u.is_admin, FALSE) = FALSE
                      AND u.premium_expiry_date IS NOT NULL
                      AND u.premium_expiry_date <= DATE_ADD(NOW(), INTERVAL 14 DAY)
                    GROUP BY u.id, u.username, u.full_name, u.avatar_url, u.premium_expiry_date
                    ORDER BY u.premium_expiry_date ASC
                    LIMIT 80
                    """
                )
                reminder_users = cursor.fetchall()
        except Exception as e:
            print(f"Error loading payments: {e}")
        finally:
            conn.close()

    return render_template(
        'admin/manage_payments.html',
        admin=admin,
        payments=payments,
        analytics=analytics,
        reminder_settings=reminder_settings,
        reminder_users=reminder_users,
        active_page='payments'
    )


@app.route('/admin/subscription-reminders/settings', methods=['POST'])
def admin_subscription_reminder_settings():
    admin, response = admin_required()
    if response:
        return response
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_subscription_reminder_schema(cursor)
                save_admin_setting(cursor, 'subscription_reminders_enabled', 'on' if request.form.get('enabled') == 'on' else 'off')
                save_admin_setting(cursor, 'subscription_reminder_7', 'on' if request.form.get('before_7') == 'on' else 'off')
                save_admin_setting(cursor, 'subscription_reminder_3', 'on' if request.form.get('before_3') == 'on' else 'off')
                save_admin_setting(cursor, 'subscription_reminder_1', 'on' if request.form.get('before_1') == 'on' else 'off')
                save_admin_setting(cursor, 'subscription_reminder_expired', 'on' if request.form.get('expired') == 'on' else 'off')
                record_admin_activity(cursor, admin=admin, action_type='subscription_reminder_settings', action_title='Subscription reminder settings saved', action_description='Admin updated automatic subscription reminder settings.', target_type='settings')
                conn.commit()
                flash('Subscription reminder settings saved.', 'success')
        except Exception as e:
            print(f"Error saving subscription reminder settings: {e}")
            flash('Unable to save reminder settings.', 'error')
        finally:
            conn.close()
    return redirect(url_for('manage_payments_page'))


@app.route('/admin/subscription-reminders/send/<int:user_id>', methods=['POST'])
def admin_send_subscription_reminder(user_id):
    admin, response = admin_required()
    if response:
        return response
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_subscription_reminder_schema(cursor)
                cursor.execute(
                    "SELECT id, username, full_name, premium_expiry_date FROM users WHERE id = %s AND COALESCE(is_admin, FALSE) = FALSE LIMIT 1",
                    (user_id,)
                )
                user_row = cursor.fetchone()
                if not user_row or not user_row.get('premium_expiry_date'):
                    flash('No active subscription expiry found for this user.', 'error')
                else:
                    send_subscription_reminder(cursor, user_row, force=True)
                    record_admin_activity(cursor, admin=admin, action_type='subscription_reminder_manual', action_title='Subscription reminder sent', action_description=f'Reminder sent to @{user_row.get("username")}.', target_type='user', target_id=user_id, target_name=user_row.get('username'))
                    conn.commit()
                    flash('Subscription reminder sent.', 'success')
        except Exception as e:
            print(f"Error sending subscription reminder: {e}")
            flash('Unable to send reminder.', 'error')
        finally:
            conn.close()
    return redirect(url_for('manage_payments_page'))


@app.route('/admin/notifications')
def admin_notifications_page():
    admin, response = admin_required()
    if response:
        return response

    status_filter = request.args.get('filter', 'all').lower()
    if status_filter not in ('all', 'unread', 'read'):
        status_filter = 'all'

    notifications = []
    users = []
    counts = {'all': 0, 'unread': 0, 'read': 0}
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                conn.commit()
                cursor.execute("SELECT COUNT(*) AS count FROM admin_notifications")
                counts['all'] = cursor.fetchone()['count']
                cursor.execute("SELECT COUNT(*) AS count FROM admin_notifications WHERE is_read = FALSE")
                counts['unread'] = cursor.fetchone()['count']
                counts['read'] = counts['all'] - counts['unread']

                where_clause = ''
                if status_filter == 'unread':
                    where_clause = 'WHERE is_read = FALSE'
                elif status_filter == 'read':
                    where_clause = 'WHERE is_read = TRUE'
                cursor.execute(
                    f"""
                    SELECT id, notification_type, title, message, related_id, icon, is_read, created_at, read_at
                    FROM admin_notifications
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT 200
                    """
                )
                notifications = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT id, username, full_name, email
                    FROM users
                    WHERE COALESCE(is_admin, FALSE) = FALSE
                      AND COALESCE(is_deleted, FALSE) = FALSE
                    ORDER BY username ASC
                    LIMIT 500
                    """
                )
                users = cursor.fetchall()
        except Exception as e:
            print(f"Error loading admin notifications: {e}")
        finally:
            conn.close()

    return render_template(
        'admin/notifications.html',
        admin=admin,
        notifications=notifications,
        users=users,
        counts=counts,
        status_filter=status_filter,
        active_page='notifications'
    )


@app.route('/admin/notifications/send', methods=['POST'])
def admin_send_user_notification():
    admin, response = admin_required()
    if response:
        return response

    target = request.form.get('target', 'all')
    user_id = request.form.get('user_id', type=int)
    title = (request.form.get('title') or '').strip()
    message = (request.form.get('message') or '').strip()
    notification_type = (request.form.get('notification_type') or 'admin').strip() or 'admin'
    if not title or not message:
        flash('Title and message are required.', 'error')
        return redirect(url_for('admin_notifications_page'))
    if target == 'one' and not user_id:
        flash('Please choose a user for selected-user notification.', 'error')
        return redirect(url_for('admin_notifications_page'))

    conn = get_db_connection()
    sent_count = 0
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_engagement_schema(cursor)
                if target == 'one' and user_id:
                    cursor.execute(
                        """
                        SELECT id FROM users
                        WHERE id = %s AND COALESCE(is_admin, FALSE) = FALSE AND COALESCE(is_deleted, FALSE) = FALSE
                        """,
                        (user_id,)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id FROM users
                        WHERE COALESCE(is_admin, FALSE) = FALSE AND COALESCE(is_deleted, FALSE) = FALSE
                        """
                    )
                for row in cursor.fetchall():
                    create_user_notification(cursor, row['id'], notification_type, title, message)
                    sent_count += 1
                create_admin_notification(
                    cursor,
                    'system',
                    'User notification sent',
                    f'{admin["username"]} sent "{title}" to {sent_count} user(s).',
                    icon='fa-solid fa-paper-plane'
                )
                record_admin_activity(cursor, admin=admin, action_type='notification_sent', action_title='Notification sent', action_description=f'Notification "{title}" sent to {sent_count} user(s).', target_type='notification', target_name=title)
                conn.commit()
                flash(f'Notification sent to {sent_count} user(s).', 'success')
        except Exception as e:
            print(f"Error sending user notification: {e}")
            flash('Unable to send user notification.', 'error')
        finally:
            conn.close()
    return redirect(url_for('admin_notifications_page'))


@app.route('/admin/notifications/<int:notification_id>/<action>', methods=['POST'])
def admin_notification_action(notification_id, action):
    admin, response = admin_required()
    if response:
        return response
    if action not in ('read', 'delete'):
        return redirect(url_for('admin_notifications_page'))

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                if action == 'read':
                    cursor.execute("UPDATE admin_notifications SET is_read = TRUE, read_at = NOW() WHERE id = %s", (notification_id,))
                elif action == 'delete':
                    cursor.execute("DELETE FROM admin_notifications WHERE id = %s", (notification_id,))
                conn.commit()
        finally:
            conn.close()
    return redirect(request.referrer or url_for('admin_notifications_page'))


@app.route('/admin/notifications/mark-all-read', methods=['POST'])
def admin_notifications_mark_all_read():
    admin, response = admin_required()
    if response:
        return response

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                cursor.execute("UPDATE admin_notifications SET is_read = TRUE, read_at = NOW() WHERE is_read = FALSE")
                conn.commit()
                flash('All notifications marked as read.', 'success')
        finally:
            conn.close()
    return redirect(request.referrer or url_for('admin_notifications_page'))


@app.route('/admin/settings', methods=['GET', 'POST'])
def admin_settings_page():
    admin, response = admin_required()
    if response:
        return response
    settings = {
        'platform_name': 'SkillFlow',
        'admin_username': admin.get('username', ADMIN_USERNAME),
        'phonepe_client_id': PHONEPE_CLIENT_ID,
        'phonepe_client_secret': PHONEPE_CLIENT_SECRET,
    }
    conn = get_db_connection()
    if not conn:
        flash('Database connection failed.', 'error')
        return render_template('admin/settings.html', admin=admin, settings=settings, active_page='settings')

    if request.method == 'POST':
        action = request.form.get('action', 'save_settings')
        platform_name = request.form.get('platform_name', 'SkillFlow').strip() or 'SkillFlow'
        admin_username = request.form.get('admin_username', ADMIN_USERNAME).strip() or ADMIN_USERNAME
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')

        try:
            with conn.cursor() as cursor:
                config = get_admin_config(cursor)
                save_admin_setting(cursor, 'platform_name', platform_name)
                save_admin_setting(cursor, 'admin_username', admin_username)
                save_admin_setting(cursor, 'phonepe_client_id', request.form.get('phonepe_client_id', '').strip())
                phonepe_client_secret = request.form.get('phonepe_client_secret', '').strip()
                if phonepe_client_secret:
                    save_admin_setting(cursor, 'phonepe_client_secret', phonepe_client_secret)
                save_admin_setting(cursor, 'phonepe_merchant_id', request.form.get('phonepe_merchant_id', '').strip())
                save_admin_setting(cursor, 'phonepe_payment_mode', request.form.get('phonepe_payment_mode', 'test').strip() or 'test')

                logo = request.files.get('platform_logo')
                if logo and logo.filename:
                    logo_filename = secure_filename(logo.filename)
                    logo_ext = os.path.splitext(logo_filename)[1].lower()
                    if logo_ext not in ('.png', '.jpg', '.jpeg', '.webp'):
                        flash('Logo upload must be a PNG, JPG, JPEG, or WEBP image.', 'error')
                        return redirect(url_for('admin_settings_page'))
                    logo.seek(0, os.SEEK_END)
                    logo_size = logo.tell()
                    logo.seek(0)
                    if logo_size > 2 * 1024 * 1024:
                        flash('Logo upload must be 2MB or smaller.', 'error')
                        return redirect(url_for('admin_settings_page'))
                    logo_dir = os.path.join(app.static_folder, 'uploads', 'admin')
                    os.makedirs(logo_dir, exist_ok=True)
                    saved_logo = f"platform-logo-{datetime.now().strftime('%Y%m%d%H%M%S')}{logo_ext}"
                    logo.save(os.path.join(logo_dir, saved_logo))
                    save_admin_setting(cursor, 'platform_logo', f"uploads/admin/{saved_logo}")

                direct_settings = {
                    'website_tagline': request.form.get('website_tagline', '').strip(),
                    'maintenance_mode': 'on' if request.form.get('maintenance_mode') == 'on' else 'off',
                    'chat_unlock_price': request.form.get('chat_unlock_price', '').strip(),
                    'currency': request.form.get('currency', 'INR').strip() or 'INR',
                    'sender_email': request.form.get('sender_email', '').strip(),
                    'smtp_host': request.form.get('smtp_host', '').strip(),
                    'smtp_port': request.form.get('smtp_port', '').strip(),
                    'otp_expiry_time': request.form.get('otp_expiry_time', '').strip(),
                    'resend_otp_cooldown': request.form.get('resend_otp_cooldown', '').strip(),
                    'session_timeout': request.form.get('session_timeout', '').strip(),
                    'user_registration_enabled': 'on' if request.form.get('user_registration_enabled') == 'on' else 'off',
                    'email_notifications_enabled': 'on' if request.form.get('email_notifications_enabled') == 'on' else 'off',
                    'admin_alerts_enabled': 'on' if request.form.get('admin_alerts_enabled') == 'on' else 'off',
                    'payment_notifications_enabled': 'on' if request.form.get('payment_notifications_enabled') == 'on' else 'off',
                    'appearance_mode': request.form.get('appearance_mode', 'light'),
                    'primary_theme_color': request.form.get('primary_theme_color', '#2563EB'),
                    'accent_color': request.form.get('accent_color', '#22C55E'),
                }
                for key, value in direct_settings.items():
                    save_admin_setting(cursor, key, value)

                if new_password:
                    if len(new_password) < 8:
                        flash('New password must be at least 8 characters.', 'error')
                        return redirect(url_for('admin_settings_page'))
                    if not current_password or not check_password_hash(config['admin_password_hash'], current_password):
                        flash('Current password is incorrect.', 'error')
                        return redirect(url_for('admin_settings_page'))
                    save_admin_setting(cursor, 'admin_password_hash', generate_password_hash(new_password))

                if action == 'backup_now':
                    save_admin_setting(cursor, 'last_backup_time', datetime.now().strftime('%d %b %Y, %I:%M %p'))
                    activity_type = 'settings_backup'
                    activity_title = 'Settings backup updated'
                    activity_description = 'Admin updated the backup timestamp.'
                elif action == 'test_email':
                    activity_type = 'settings_test_email'
                    activity_title = 'Email settings tested'
                    activity_description = 'Admin saved and tested email settings.'
                else:
                    activity_type = 'settings_saved'
                    activity_title = 'Settings saved'
                    activity_description = 'Admin saved platform settings.'

                record_admin_activity(cursor, admin=admin, action_type=activity_type, action_title=activity_title, action_description=activity_description, target_type='settings')

                conn.commit()
                session['admin_username'] = admin_username
                if action == 'test_email':
                    sender_email = direct_settings.get('sender_email')
                    smtp_host = direct_settings.get('smtp_host')
                    smtp_port = direct_settings.get('smtp_port')
                    if sender_email and smtp_host and smtp_port:
                        flash('Email settings look ready. SMTP details saved successfully.', 'success')
                    else:
                        flash('Please add sender email, SMTP host, and SMTP port before testing email.', 'error')
                elif action == 'backup_now':
                    flash('Backup timestamp updated successfully.', 'success')
                else:
                    flash('Settings saved successfully.', 'success')
                return redirect(url_for('admin_settings_page'))
        except Exception as e:
            print(f"Error saving admin settings: {e}")
            flash('Unable to save settings.', 'error')
        finally:
            conn.close()
        return redirect(url_for('admin_settings_page'))

    try:
        with conn.cursor() as cursor:
            settings = get_admin_config(cursor)
            conn.commit()
    except Exception as e:
        print(f"Error loading admin settings: {e}")
    finally:
        conn.close()
    return render_template('admin/settings.html', admin=admin, settings=settings, active_page='settings')


@app.route('/admin/plans/<int:plan_id>/toggle', methods=['POST'])
def admin_toggle_plan(plan_id):
    admin, response = admin_required()
    if response:
        return response

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                cursor.execute("UPDATE platform_plans SET is_active = NOT is_active WHERE id = %s", (plan_id,))
                conn.commit()
        finally:
            conn.close()
    return redirect(url_for('manage_payments_page'))


@app.route('/admin/reports')
def admin_reports_page():
    admin, response = admin_required()
    if response:
        return response

    reports = []
    report_stats = {
        'users_by_location': [],
        'requests_by_status': [],
        'payments_by_status': [],
    }
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                conn.commit()
                cursor.execute(
                    """
                    SELECT r.id, r.reason, r.description, r.status, r.created_at,
                           COALESCE(r.reporter_username, reporter.username, CONCAT('User #', COALESCE(r.reported_by, r.reporter_user_id))) AS reporter_name,
                           COALESCE(r.reported_username, reported.username, CONCAT('User #', r.reported_user_id)) AS reported_name,
                           r.reported_user_id
                    FROM reports r
                    LEFT JOIN users reporter ON reporter.id = COALESCE(r.reported_by, r.reporter_user_id)
                    LEFT JOIN users reported ON reported.id = r.reported_user_id
                    ORDER BY r.created_at DESC
                    """
                )
                reports = cursor.fetchall()
                cursor.execute(
                    "SELECT COALESCE(location, 'Not set') AS label, COUNT(*) AS count FROM users GROUP BY label ORDER BY count DESC LIMIT 10"
                )
                report_stats['users_by_location'] = cursor.fetchall()
                cursor.execute("SELECT status AS label, COUNT(*) AS count FROM requests GROUP BY status")
                report_stats['requests_by_status'] = cursor.fetchall()
                if table_exists(cursor, 'payments'):
                    cursor.execute("SELECT status AS label, COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total FROM payments GROUP BY status")
                    report_stats['payments_by_status'] = cursor.fetchall()
        except Exception as e:
            print(f"Error loading reports: {e}")
        finally:
            conn.close()

    return render_template('admin/manage_reports.html', admin=admin, reports=reports, report=report_stats, active_page='reports')


@app.route('/admin/reviews')
def admin_reviews_page():
    admin, response = admin_required()
    if response:
        return response

    reviews = []
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                ensure_engagement_schema(cursor)
                cursor.execute(
                    """
                    SELECT rv.id, rv.rating, rv.feedback, rv.experience_tag, rv.status, rv.created_at,
                           reviewer.username AS reviewer_username,
                           reviewer.full_name AS reviewer_name,
                           reviewed.username AS reviewed_username,
                           reviewed.full_name AS reviewed_name
                    FROM user_reviews rv
                    JOIN users reviewer ON reviewer.id = rv.reviewer_id
                    JOIN users reviewed ON reviewed.id = rv.reviewed_user_id
                    ORDER BY rv.created_at DESC
                    """
                )
                reviews = cursor.fetchall()
        except Exception as e:
            print(f"Error loading reviews: {e}")
        finally:
            conn.close()

    return render_template('admin/manage_reviews.html', admin=admin, reviews=reviews, active_page='reviews')


@app.route('/admin/reviews/<int:review_id>/<action>', methods=['POST'])
def admin_review_action(review_id, action):
    admin, response = admin_required()
    if response:
        return response
    if action not in ('visible', 'remove', 'delete'):
        return redirect(url_for('admin_reviews_page'))

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_engagement_schema(cursor)
                if action == 'delete':
                    cursor.execute("DELETE FROM user_reviews WHERE id = %s", (review_id,))
                    action_text = 'deleted'
                else:
                    next_status = 'visible' if action == 'visible' else 'removed'
                    cursor.execute("UPDATE user_reviews SET status = %s WHERE id = %s", (next_status, review_id))
                    action_text = next_status
                create_admin_notification(
                    cursor,
                    'review',
                    'Review moderated',
                    f'{admin["username"]} marked review #{review_id} as {action_text}.',
                    related_id=review_id,
                    icon='fa-solid fa-star'
                )
                conn.commit()
        finally:
            conn.close()
    return redirect(url_for('admin_reviews_page'))


@app.route('/admin/reports/<int:report_id>/<action>', methods=['POST'])
def admin_report_action(report_id, action):
    admin, response = admin_required()
    if response:
        return response

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                cursor.execute("SELECT id, reporter_id, reported_user_id, report_type, description, status FROM reports WHERE id = %s", (report_id,))
                report_row = cursor.fetchone()
                if action == 'reviewed':
                    cursor.execute("UPDATE reports SET status = 'under_review' WHERE id = %s", (report_id,))
                    activity_type = 'report_reviewed'
                    activity_title = 'Report marked reviewed'
                elif action == 'resolved':
                    cursor.execute("UPDATE reports SET status = 'resolved' WHERE id = %s", (report_id,))
                    activity_type = 'report_resolved'
                    activity_title = 'Report resolved'
                elif action == 'block':
                    if report_row:
                        cursor.execute("UPDATE users SET is_blocked = TRUE WHERE id = %s AND is_admin = FALSE", (report_row['reported_user_id'],))
                        log_admin_action(cursor, admin['username'], report_row['reported_user_id'], 'block')
                        cursor.execute("UPDATE reports SET status = 'resolved' WHERE id = %s", (report_id,))
                    activity_type = 'report_user_blocked'
                    activity_title = 'Reported user blocked'
                elif action == 'delete':
                    cursor.execute("UPDATE reports SET status = 'resolved' WHERE id = %s", (report_id,))
                    activity_type = 'report_deleted'
                    activity_title = 'Report deleted'
                else:
                    activity_type = None
                    activity_title = None
                if activity_type and report_row:
                    record_admin_activity(
                        cursor,
                        admin=admin,
                        action_type=activity_type,
                        action_title=activity_title,
                        action_description=f'Report #{report_id} action: {action}.',
                        target_type='report',
                        target_id=report_id,
                        target_name=report_row.get('report_type')
                    )
                conn.commit()
        finally:
            conn.close()
    return redirect(url_for('admin_reports_page'))


@app.route('/admin/activity-history')
def admin_activity_history_page():
    admin, response = admin_required()
    if response:
        return response

    logs = []
    stats = {'total': 0, 'today': 0, 'user': 0, 'security': 0}
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                ensure_admin_schema(cursor)
                cursor.execute("SELECT COUNT(*) AS count FROM admin_activity_logs")
                stats['total'] = cursor.fetchone()['count']
                cursor.execute("SELECT COUNT(*) AS count FROM admin_activity_logs WHERE DATE(created_at) = CURDATE()")
                stats['today'] = cursor.fetchone()['count']
                cursor.execute("""
                    SELECT COUNT(*) AS count FROM admin_activity_logs
                    WHERE target_type = 'user' OR action_type IN ('block','unblock','delete','restore','manual_email_verify','user_blocked','user_unblocked','user_deleted','user_restored')
                """)
                stats['user'] = cursor.fetchone()['count']
                cursor.execute("""
                    SELECT COUNT(*) AS count FROM admin_activity_logs
                    WHERE action_type IN ('admin_login','admin_logout','settings_saved','settings_backup','settings_test_email')
                       OR action_type LIKE '%security%'
                """)
                stats['security'] = cursor.fetchone()['count']
                cursor.execute("""
                    SELECT id, admin_id, admin_name, action_type, action_title, action_description,
                           target_type, target_id, target_name, ip_address, created_at
                    FROM admin_activity_logs
                    ORDER BY created_at DESC
                    LIMIT 500
                """)
                logs = cursor.fetchall()
        except Exception as e:
            print(f"Error loading admin activity history: {e}")
            flash('Unable to load activity history.', 'error')
        finally:
            conn.close()

    return render_template(
        'admin/activity_history.html',
        admin=admin,
        logs=logs,
        stats=stats,
        active_page='activity_history'
    )

if __name__ == '__main__':
    app.run(
        debug=os.getenv('FLASK_DEBUG', '0').lower() in ('1', 'true', 'yes'),
        host=os.getenv('FLASK_HOST', '127.0.0.1'),
        port=int(os.getenv('FLASK_PORT', '5000'))
    )
