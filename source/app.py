"""
Heartbeat Monitor - Lightweight cron/backup job monitoring
Single-container, Python/Flask/SQLite, MIT licensed
"""
import os
import sqlite3
import json
import hashlib
import secrets
from datetime import datetime, timedelta
from functools import wraps
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

from flask import Flask, request, jsonify, render_template, g, redirect, url_for, flash, Response, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import threading
import time
import schedule

# Configuration
DATABASE = os.environ.get('DATABASE', '/data/heartbeat.db')
SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', secrets.token_hex(32))
RATE_LIMIT_WINDOW = int(os.environ.get('RATE_LIMIT_WINDOW', '60'))  # seconds
RATE_LIMIT_MAX = int(os.environ.get('RATE_LIMIT_MAX', '100'))  # requests per window

# Alert configuration (can be overridden per job)
DEFAULT_TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
DEFAULT_TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
DEFAULT_DISCORD_WEBHOOK = os.environ.get('DISCORD_WEBHOOK', '')
DEFAULT_SMTP_HOST = os.environ.get('SMTP_HOST', '')
DEFAULT_SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
DEFAULT_SMTP_USER = os.environ.get('SMTP_USER', '')
DEFAULT_SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
DEFAULT_SMTP_FROM = os.environ.get('SMTP_FROM', '')
DEFAULT_SMTP_TO = os.environ.get('SMTP_TO', '')
DEFAULT_SMTP_TLS = os.environ.get('SMTP_TLS', 'true').lower() == 'true'

# Job default settings
DEFAULT_GRACE_PERIOD = int(os.environ.get('DEFAULT_GRACE_PERIOD', '3600'))  # 1 hour
DEFAULT_ALERT_EVENTS = os.environ.get('DEFAULT_ALERT_EVENTS', 'overdue,failed').split(',')

def init_db():
    """Initialize database schema."""
    db = get_db()
    
    # Jobs table
    db.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            token TEXT NOT NULL UNIQUE,
            interval_seconds INTEGER NOT NULL,
            grace_period_seconds INTEGER DEFAULT 3600,
            description TEXT,
            alert_events TEXT DEFAULT 'overdue,failed',
            telegram_bot_token TEXT,
            telegram_chat_id TEXT,
            discord_webhook TEXT,
            smtp_host TEXT,
            smtp_port INTEGER,
            smtp_user TEXT,
            smtp_password TEXT,
            smtp_from TEXT,
            smtp_to TEXT,
            smtp_tls BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Heartbeats table
    db.execute('''
        CREATE TABLE IF NOT EXISTS heartbeats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            status TEXT NOT NULL,  -- 'started', 'success', 'failed'
            exit_code INTEGER,
            output TEXT,
            duration_ms INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
    ''')
    
    # Alert state table (to track what's been alerted)
    db.execute('''
        CREATE TABLE IF NOT EXISTS alert_state (
            job_id TEXT PRIMARY KEY,
            last_overdue_alert TIMESTAMP,
            last_failed_alert TIMESTAMP,
            last_recovery_alert TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
    ''')
    
    # Index for efficient queries
    db.execute('CREATE INDEX IF NOT EXISTS idx_heartbeats_job_time ON heartbeats(job_id, timestamp DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_heartbeats_status ON heartbeats(status)')
    
    db.commit()


def hash_token(token: str) -> str:
    """Hash a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    """Verify a token against its hash."""
    return hash_token(token) == token_hash


def generate_job_token() -> tuple[str, str]:
    """Generate a new job token and its hash."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


@contextmanager
def rate_limit(key: str):
    """Context manager for rate limiting."""
    now = time.time()
    with rate_limit_lock:
        if key not in rate_limit_store:
            rate_limit_store[key] = []
        
        # Clean old entries
        cutoff = now - RATE_LIMIT_WINDOW
        rate_limit_store[key] = [t for t in rate_limit_store[key] if t > cutoff]
        
        if len(rate_limit_store[key]) >= RATE_LIMIT_MAX:
            raise Exception('Rate limit exceeded')
        
        rate_limit_store[key].append(now)
    
    try:
        yield
    finally:
        pass


def require_admin_token(f):
    """Decorator to require admin token for management endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Admin-Token') or request.args.get('admin_token')
        if token != ADMIN_TOKEN:
            return jsonify({'error': 'Invalid admin token'}), 401
        return f(*args, **kwargs)
    return decorated


def send_telegram_alert(bot_token: str, chat_id: str, message: str) -> bool:
    """Send Telegram alert."""
    if not bot_token or not chat_id:
        return False
    try:
        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        data = {'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'}
        resp = requests.post(url, json=data, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def send_discord_alert(webhook_url: str, message: str) -> bool:
    """Send Discord webhook alert."""
    if not webhook_url:
        return False
    try:
        data = {'content': message}
        resp = requests.post(webhook_url, json=data, timeout=10)
        return resp.status_code in (200, 204)
    except Exception:
        return False


def send_email_alert(smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str,
                     smtp_from: str, smtp_to: str, smtp_tls: bool,
                     subject: str, body: str) -> bool:
    """Send email alert."""
    if not all([smtp_host, smtp_user, smtp_password, smtp_from, smtp_to]):
        return False
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        msg = MIMEMultipart()
        msg['From'] = smtp_from
        msg['To'] = smtp_to
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(smtp_host, smtp_port)
        if smtp_tls:
            server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception:
        return False


def send_alert(job: Dict[str, Any], event: str, details: str = '') -> bool:
    """Send alert for a job event."""
    sent_any = False
    job_name = job['name']
    
    # Build message
    if event == 'overdue':
        message = f'⚠️ <b>Job Overdue</b>\n\nJob: <code>{job_name}</code>\nExpected interval: {job["interval_seconds"]//60} min\nGrace period: {job["grace_period_seconds"]//60} min\nLast run: {details or "unknown"}'
        subject = f'[Heartbeat] Job Overdue: {job_name}'
    elif event == 'failed':
        message = f'❌ <b>Job Failed</b>\n\nJob: <code>{job_name}</code>\nExit code: {details}\nTime: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
        subject = f'[Heartbeat] Job Failed: {job_name}'
    elif event == 'recovery':
        message = f'✅ <b>Job Recovered</b>\n\nJob: <code>{job_name}</code>\nNow running normally.\nTime: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
        subject = f'[Heartbeat] Job Recovered: {job_name}'
    else:
        return False
    
    # Telegram
    if job.get('telegram_bot_token') and job.get('telegram_chat_id'):
        if send_telegram_alert(job['telegram_bot_token'], job['telegram_chat_id'], message):
            sent_any = True
    elif DEFAULT_TELEGRAM_BOT_TOKEN and DEFAULT_TELEGRAM_CHAT_ID:
        if send_telegram_alert(DEFAULT_TELEGRAM_BOT_TOKEN, DEFAULT_TELEGRAM_CHAT_ID, message):
            sent_any = True
    
    # Discord
    if job.get('discord_webhook'):
        if send_discord_alert(job['discord_webhook'], message):
            sent_any = True
    elif DEFAULT_DISCORD_WEBHOOK:
        if send_discord_alert(DEFAULT_DISCORD_WEBHOOK, message):
            sent_any = True
    
    # Email
    smtp_host = job.get('smtp_host') or DEFAULT_SMTP_HOST
    smtp_port = job.get('smtp_port') or DEFAULT_SMTP_PORT
    smtp_user = job.get('smtp_user') or DEFAULT_SMTP_USER
    smtp_password = job.get('smtp_password') or DEFAULT_SMTP_PASSWORD
    smtp_from = job.get('smtp_from') or DEFAULT_SMTP_FROM
    smtp_to = job.get('smtp_to') or DEFAULT_SMTP_TO
    smtp_tls = job.get('smtp_tls', DEFAULT_SMTP_TLS)
    
    if all([smtp_host, smtp_user, smtp_password, smtp_from, smtp_to]):
        if send_email_alert(smtp_host, smtp_port, smtp_user, smtp_password,
                           smtp_from, smtp_to, smtp_tls, subject, message):
            sent_any = True
    
    return sent_any


def check_overdue_jobs():
    """Background task to check for overdue jobs."""
    db = get_db()
    now = datetime.now()
    
    jobs = db.execute('SELECT * FROM jobs').fetchall()
    
    for job in jobs:
        job_dict = dict(job)
        interval = job_dict['interval_seconds']
        grace = job_dict['grace_period_seconds']
        alert_events = job_dict['alert_events'].split(',') if job_dict['alert_events'] else []
        
        # Get last heartbeat
        last_hb = db.execute(
            'SELECT * FROM heartbeats WHERE job_id = ? ORDER BY timestamp DESC LIMIT 1',
            (job_dict['id'],)
        ).fetchone()
        
        # Get alert state
        alert_state = db.execute(
            'SELECT * FROM alert_state WHERE job_id = ?', (job_dict['id'],)
        ).fetchone()
        
        if not alert_state:
            db.execute('INSERT INTO alert_state (job_id) VALUES (?)', (job_dict['id'],))
            db.commit()
            alert_state = db.execute(
                'SELECT * FROM alert_state WHERE job_id = ?', (job_dict['id'],)
            ).fetchone()
        
        if not last_hb:
            # Never ran - check if overdue from creation
            created = datetime.fromisoformat(job_dict['created_at'])
            if (now - created).total_seconds() > interval + grace:
                if 'overdue' in alert_events and not alert_state['last_overdue_alert']:
                    send_alert(job_dict, 'overdue', 'never ran')
                    db.execute(
                        'UPDATE alert_state SET last_overdue_alert = ? WHERE job_id = ?',
                        (now.isoformat(), job_dict['id'])
                    )
                    db.commit()
        else:
            last_run = datetime.fromisoformat(last_hb['timestamp'])
            time_since_last = (now - last_run).total_seconds()
            
            # Check overdue
            if time_since_last > interval + grace:
                if 'overdue' in alert_events and not alert_state['last_overdue_alert']:
                    send_alert(job_dict, 'overdue', last_run.strftime('%Y-%m-%d %H:%M:%S'))
                    db.execute(
                        'UPDATE alert_state SET last_overdue_alert = ? WHERE job_id = ?',
                        (now.isoformat(), job_dict['id'])
                    )
                    db.commit()
            else:
                # Recovery from overdue
                if alert_state['last_overdue_alert'] and 'overdue' in alert_events:
                    send_alert(job_dict, 'recovery')
                    db.execute(
                        'UPDATE alert_state SET last_overdue_alert = NULL WHERE job_id = ?',
                        (job_dict['id'],)
                    )
                    db.commit()
            
            # Check failed
            if last_hb['status'] == 'failed':
                if 'failed' in alert_events and not alert_state['last_failed_alert']:
                    send_alert(job_dict, 'failed', str(last_hb['exit_code'] or 'unknown'))
                    db.execute(
                        'UPDATE alert_state SET last_failed_alert = ? WHERE job_id = ?',
                        (now.isoformat(), job_dict['id'])
                    )
                    db.commit()
            else:
                # Recovery from failed
                if alert_state['last_failed_alert'] and 'failed' in alert_events:
                    send_alert(job_dict, 'recovery')
                    db.execute(
                        'UPDATE alert_state SET last_failed_alert = NULL WHERE job_id = ?',
                        (job_dict['id'],)
                    )
                    db.commit()


def run_scheduler():
    """Run the background scheduler."""
    schedule.every(1).minutes.do(check_overdue_jobs)
    
    while True:
        schedule.run_pending()
        time.sleep(10)


app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['DATABASE'] = DATABASE

# Rate limiting storage
rate_limit_store = {}
rate_limit_lock = threading.Lock()


def get_db():
    """Get database connection."""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()




# ==================== API Routes ====================

@app.route('/healthz')
def healthz():
    """Health check endpoint."""
    return jsonify({'status': 'healthy', 'database': 'connected'})


@app.route('/health')
def health():
    """Health check endpoint (alternative path)."""
    return jsonify({'status': 'healthy', 'database': 'connected'})


@app.route('/api/heartbeat/<token>', methods=['POST'])
def receive_heartbeat(token):
    """Receive a heartbeat from a job."""
    try:
        with rate_limit(request.remote_addr or 'unknown'):
            pass
    except Exception:
        return jsonify({'error': 'Rate limit exceeded'}), 429
    
    # Find job by token hash
    token_hash = hash_token(token)
    db = get_db()
    job = db.execute('SELECT * FROM jobs WHERE token = ?', (token_hash,)).fetchone()
    
    if not job:
        return jsonify({'error': 'Invalid token'}), 404
    
    job_dict = dict(job)
    data = request.get_json() or {}
    status = data.get('status', 'success')  # 'started', 'success', 'failed'
    exit_code = data.get('exit_code')
    output = data.get('output', '')[:10000]  # Limit output size
    duration_ms = data.get('duration_ms')
    
    # Insert heartbeat
    db.execute('''
        INSERT INTO heartbeats (job_id, status, exit_code, output, duration_ms)
        VALUES (?, ?, ?, ?, ?)
    ''', (job_dict['id'], status, exit_code, output, duration_ms))
    
    # If job just succeeded, clear failed alert state
    if status == 'success':
        db.execute(
            'UPDATE alert_state SET last_failed_alert = NULL WHERE job_id = ?',
            (job_dict['id'],)
        )
        # Also clear overdue if it was alerted
        db.execute(
            'UPDATE alert_state SET last_overdue_alert = NULL WHERE job_id = ?',
            (job_dict['id'],)
        )
    
    db.commit()
    
    return jsonify({'status': 'received', 'job': job_dict['name']})


@app.route('/api/jobs', methods=['GET'])
@require_admin_token
def list_jobs():
    """List all jobs with their latest status."""
    db = get_db()
    jobs = db.execute('SELECT * FROM jobs ORDER BY created_at DESC').fetchall()
    
    result = []
    for job in jobs:
        job_dict = dict(job)
        job_dict['token'] = '***'  # Don't expose token
        
        # Get latest heartbeat
        last_hb = db.execute(
            'SELECT * FROM heartbeats WHERE job_id = ? ORDER BY timestamp DESC LIMIT 1',
            (job_dict['id'],)
        ).fetchone()
        
        if last_hb:
            job_dict['last_run'] = dict(last_hb)
            # Determine current status
            interval = job_dict['interval_seconds']
            grace = job_dict['grace_period_seconds']
            last_run = datetime.fromisoformat(last_hb['timestamp'])
            time_since = (datetime.now() - last_run).total_seconds()
            
            if last_hb['status'] == 'failed':
                job_dict['current_status'] = 'failed'
            elif time_since > interval + grace:
                job_dict['current_status'] = 'overdue'
            elif time_since > interval:
                job_dict['current_status'] = 'late'
            else:
                job_dict['current_status'] = 'ok'
        else:
            job_dict['last_run'] = None
            created = datetime.fromisoformat(job_dict['created_at'])
            time_since = (datetime.now() - created).total_seconds()
            if time_since > job_dict['interval_seconds'] + job_dict['grace_period_seconds']:
                job_dict['current_status'] = 'overdue'
            else:
                job_dict['current_status'] = 'pending'
        
        result.append(job_dict)
    
    return jsonify(result)


@app.route('/api/jobs', methods=['POST'])
@require_admin_token
def create_job():
    """Create a new job."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    name = data.get('name')
    interval_seconds = data.get('interval_seconds')
    grace_period_seconds = data.get('grace_period_seconds', DEFAULT_GRACE_PERIOD)
    description = data.get('description', '')
    alert_events = data.get('alert_events', DEFAULT_ALERT_EVENTS)
    
    if not name or not interval_seconds:
        return jsonify({'error': 'name and interval_seconds required'}), 400
    
    try:
        interval_seconds = int(interval_seconds)
        grace_period_seconds = int(grace_period_seconds)
    except ValueError:
        return jsonify({'error': 'interval_seconds and grace_period_seconds must be integers'}), 400
    
    if interval_seconds < 60:
        return jsonify({'error': 'interval_seconds must be at least 60'}), 400
    
    token, token_hash = generate_job_token()
    
    db = get_db()
    try:
        db.execute('''
            INSERT INTO jobs (id, name, token, interval_seconds, grace_period_seconds, 
                             description, alert_events,
                             telegram_bot_token, telegram_chat_id, discord_webhook,
                             smtp_host, smtp_port, smtp_user, smtp_password,
                             smtp_from, smtp_to, smtp_tls)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            hashlib.sha256(name.encode()).hexdigest()[:32],
            name,
            token_hash,
            interval_seconds,
            grace_period_seconds,
            description,
            ','.join(alert_events) if isinstance(alert_events, list) else alert_events,
            data.get('telegram_bot_token', ''),
            data.get('telegram_chat_id', ''),
            data.get('discord_webhook', ''),
            data.get('smtp_host', ''),
            data.get('smtp_port', DEFAULT_SMTP_PORT),
            data.get('smtp_user', ''),
            data.get('smtp_password', ''),
            data.get('smtp_from', ''),
            data.get('smtp_to', ''),
            data.get('smtp_tls', True)
        ))
        db.execute('INSERT INTO alert_state (job_id) VALUES (?)', (hashlib.sha256(name.encode()).hexdigest()[:32],))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Job name already exists'}), 409
    
    return jsonify({'id': hashlib.sha256(name.encode()).hexdigest()[:32], 'name': name, 'token': token}), 201


@app.route('/api/jobs/<job_id>', methods=['GET'])
@require_admin_token
def get_job(job_id):
    """Get job details."""
    db = get_db()
    job = db.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
    
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    job_dict = dict(job)
    job_dict['token'] = '***'
    
    return jsonify(job_dict)


@app.route('/api/jobs/<job_id>', methods=['PUT'])
@require_admin_token
def update_job(job_id):
    """Update a job."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    db = get_db()
    job = db.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
    
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    # Build update query
    fields = []
    values = []
    
    for field in ['name', 'interval_seconds', 'grace_period_seconds', 'description',
                  'alert_events', 'telegram_bot_token', 'telegram_chat_id', 'discord_webhook',
                  'smtp_host', 'smtp_port', 'smtp_user', 'smtp_password',
                  'smtp_from', 'smtp_to', 'smtp_tls']:
        if field in data:
            if field == 'alert_events' and isinstance(data[field], list):
                fields.append(f'{field} = ?')
                values.append(','.join(data[field]))
            else:
                fields.append(f'{field} = ?')
                values.append(data[field])
    
    if not fields:
        return jsonify({'error': 'No valid fields to update'}), 400
    
    fields.append('updated_at = CURRENT_TIMESTAMP')
    values.append(job_id)
    
    try:
        db.execute(f'UPDATE jobs SET {", ".join(fields)} WHERE id = ?', values)
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Job name already exists'}), 409
    
    return jsonify({'status': 'updated'})


@app.route('/api/jobs/<job_id>', methods=['DELETE'])
@require_admin_token
def delete_job(job_id):
    """Delete a job."""
    db = get_db()
    db.execute('DELETE FROM jobs WHERE id = ?', (job_id,))
    db.execute('DELETE FROM alert_state WHERE job_id = ?', (job_id,))
    db.commit()
    return jsonify({'status': 'deleted'})


@app.route('/api/jobs/<job_id>/history', methods=['GET'])
@require_admin_token
def job_history(job_id):
    """Get job heartbeat history."""
    db = get_db()
    limit = min(int(request.args.get('limit', 100)), 1000)
    
    heartbeats = db.execute(
        'SELECT * FROM heartbeats WHERE job_id = ? ORDER BY timestamp DESC LIMIT ?',
        (job_id, limit)
    ).fetchall()
    
    return jsonify([dict(h) for h in heartbeats])


@app.route('/api/jobs/<job_id>/stats', methods=['GET'])
@require_admin_token
def job_stats(job_id):
    """Get job statistics (last 7 days)."""
    db = get_db()
    since = (datetime.now() - timedelta(days=7)).isoformat()
    
    stats = db.execute('''
        SELECT 
            date(timestamp) as day,
            COUNT(*) as total_runs,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
            AVG(duration_ms) as avg_duration_ms
        FROM heartbeats
        WHERE job_id = ? AND timestamp >= ?
        GROUP BY date(timestamp)
        ORDER BY day DESC
    ''', (job_id, since)).fetchall()
    
    return jsonify([dict(s) for s in stats])


# ==================== Web Dashboard ====================

@app.route('/')
def dashboard():
    """Main dashboard."""
    db = get_db()
    jobs = db.execute('SELECT * FROM jobs ORDER BY created_at DESC').fetchall()
    
    jobs_data = []
    for job in jobs:
        job_dict = dict(job)
        
        last_hb = db.execute(
            'SELECT * FROM heartbeats WHERE job_id = ? ORDER BY timestamp DESC LIMIT 1',
            (job_dict['id'],)
        ).fetchone()
        
        if last_hb:
            job_dict['last_run'] = dict(last_hb)
            interval = job_dict['interval_seconds']
            grace = job_dict['grace_period_seconds']
            last_run = datetime.fromisoformat(last_hb['timestamp'])
            time_since = (datetime.now() - last_run).total_seconds()
            
            if last_hb['status'] == 'failed':
                job_dict['current_status'] = 'failed'
            elif time_since > interval + grace:
                job_dict['current_status'] = 'overdue'
            elif time_since > interval:
                job_dict['current_status'] = 'late'
            else:
                job_dict['current_status'] = 'ok'
        else:
            job_dict['last_run'] = None
            created = datetime.fromisoformat(job_dict['created_at'])
            time_since = (datetime.now() - created).total_seconds()
            if time_since > job_dict['interval_seconds'] + job_dict['grace_period_seconds']:
                job_dict['current_status'] = 'overdue'
            else:
                job_dict['current_status'] = 'pending'
        
        jobs_data.append(job_dict)
    
    return render_template('dashboard.html', jobs=jobs_data, admin_token=ADMIN_TOKEN)


@app.route('/job/<job_id>')
def job_detail(job_id):
    """Job detail page."""
    db = get_db()
    job = db.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
    
    if not job:
        return 'Job not found', 404
    
    job_dict = dict(job)
    
    heartbeats = db.execute(
        'SELECT * FROM heartbeats WHERE job_id = ? ORDER BY timestamp DESC LIMIT 50',
        (job_id,)
    ).fetchall()
    
    return render_template('job_detail.html', job=job_dict, heartbeats=[dict(h) for h in heartbeats])


# ==================== CLI Wrapper Support ====================

@app.route('/cli-wrapper')
def cli_wrapper():
    """Serve the CLI wrapper script."""
    return render_template('cli_wrapper.sh'), 200, {'Content-Type': 'text/plain; charset=utf-8'}


# ==================== Comparison Page ====================

@app.route('/compare')
def compare():
    """Serve the comparison page."""
    import os
    comparison_path = os.path.join(os.path.dirname(__file__), 'COMPARISON.md')
    try:
        with open(comparison_path, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        content = 'Comparison page not found.'
    return render_template('compare.html', content=content)


# ==================== Main ====================

@app.route('/robots.txt')
def robots_txt():
    return send_file('robots.txt')


@app.route('/sitemap.xml')
def sitemap():
    db = get_db()
    cursor = db.execute("SELECT id, name, created_at FROM jobs ORDER BY created_at DESC")
    jobs = cursor.fetchall()
    
    base = "http://77.90.53.243:5002"
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    
    # Main pages
    xml.append(f'  <url><loc>{base}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>')
    xml.append(f'  <url><loc>{base}/compare</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>')
    
    # Job pages
    for job in jobs:
        xml.append(f'  <url><loc>{base}/job/{job["id"]}</loc><lastmod>{job["created_at"][:10]}</lastmod><changefreq>monthly</changefreq><priority>0.7</priority></url>')
    
    xml.append('</urlset>')
    return Response('\n'.join(xml), mimetype='application/xml')


