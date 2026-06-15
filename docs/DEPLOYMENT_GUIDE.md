# Email System - Deployment & Operations Guide

## Production Deployment Checklist

### Pre-Deployment (Development)

- [ ] Test email locally with console backend
  ```bash
  USE_SMTP_EMAIL=False python manage.py process_email_queue --limit 1
  ```

- [ ] Create and test `.env` with SMTP credentials
  ```bash
  cp .env.example .env
  # Edit .env with actual SMTP credentials
  ```

- [ ] Test SMTP connection
  ```bash
  python manage.py shell
  from django.core.mail import send_mail
  send_mail('Test', 'Test email', 'from@example.com', ['to@example.com'])
  ```

- [ ] Run migrations
  ```bash
  python manage.py migrate
  ```

- [ ] Verify logging directory exists
  ```bash
  mkdir -p logs
  ```

- [ ] Test management command locally
  ```bash
  python manage.py process_email_queue --limit 1
  ```

### Deployment Steps

#### 1. Code Deployment

```bash
# Clone/pull latest code
git pull origin main

# Create virtual environment (if needed)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create logs directory
mkdir -p logs

# Collect static files
python manage.py collectstatic --noinput
```

#### 2. Configure Environment Variables

Create `.env` file (DO NOT commit to Git):

```bash
# Email Configuration
USE_SMTP_EMAIL=True
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-specific-password

# Email Settings
DEFAULT_FROM_EMAIL=noreply@bookmyseat.com
SUPPORT_EMAIL=support@bookmyseat.com
EMAIL_TIMEOUT=10
EMAIL_MAX_ATTEMPTS=5
EMAIL_RETRY_DELAY_MINUTES=1

# Database (if using PostgreSQL)
DATABASE_URL=postgresql://user:password@host:5432/bookmyseat

# Django Settings
DEBUG=False
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
```

**Security**: 
- Store `.env` file outside version control
- Add to `.gitignore`: `echo ".env" >> .gitignore`
- Use strong, random passwords
- Rotate credentials periodically

#### 3. Setup Log Rotation

**Linux/Mac with logrotate**:

Create `/etc/logrotate.d/bookmyseat`:
```
/path/to/bookmyseat/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data www-data
    sharedscripts
    postrotate
        systemctl reload bookmyseat || true
    endscript
}
```

#### 4. Schedule Email Processing

**Option A: Cron (Linux/Mac)**

Edit crontab:
```bash
crontab -e
```

Add line:
```bash
# Process emails every 5 minutes
*/5 * * * * cd /path/to/bookmyseat && /path/to/venv/bin/python manage.py process_email_queue --limit 50 >> /path/to/logs/cron.log 2>&1

# Backup database daily at 2 AM
0 2 * * * cd /path/to/bookmyseat && /path/to/venv/bin/python manage.py dumpdata > /backups/db_$(date +\%Y\%m\%d).json

# Cleanup old logs weekly
0 0 * * 0 find /path/to/bookmyseat/logs -name "*.log" -mtime +30 -delete
```

**Option B: Windows Task Scheduler**

1. Create new task
2. Trigger: On a schedule → Repeat every 5 minutes
3. Action: 
   - Program: `C:\Python39\python.exe`
   - Arguments: `manage.py process_email_queue --limit 50`
   - Start in: `C:\path\to\bookmyseat`
4. Conditions: Run only if system is idle (unchecked)
5. Settings: Allow on-demand triggering

**Option C: Supervisor (Recommended)**

Create `/etc/supervisor/conf.d/bookmyseat-email.conf`:
```ini
[program:bookmyseat-email]
directory=/path/to/bookmyseat
command=/path/to/venv/bin/python manage.py process_email_queue --limit 50
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=10
stdout_logfile=/path/to/logs/email-supervisor.log
stderr_logfile=/path/to/logs/email-supervisor-error.log
environment=PATH="/path/to/venv/bin",USE_SMTP_EMAIL="True"
```

Then:
```bash
supervisorctl reread
supervisorctl update
supervisorctl start bookmyseat-email
```

**Option D: Systemd Timer (Modern Linux)**

Create `/etc/systemd/system/bookmyseat-email.service`:
```ini
[Unit]
Description=BookMySeat Email Queue Processor
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/path/to/bookmyseat
EnvironmentFile=/path/to/.env
ExecStart=/path/to/venv/bin/python manage.py process_email_queue --limit 50
StandardOutput=journal
StandardError=journal
SyslogIdentifier=bookmyseat-email
User=www-data
Group=www-data
```

Create `/etc/systemd/system/bookmyseat-email.timer`:
```ini
[Unit]
Description=BookMySeat Email Queue Processing Timer
Requires=bookmyseat-email.service

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
AccuracySec=1s
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start:
```bash
sudo systemctl enable bookmyseat-email.timer
sudo systemctl start bookmyseat-email.timer
sudo systemctl status bookmyseat-email.timer
```

#### 5. Setup Monitoring & Alerting

**Monitor email queue size**:
```bash
# Create monitoring script: scripts/check_email_queue.py
python check_email_queue.py
```

**Alert on failures**:
```python
# movies/email_monitoring.py
from movies.models import EmailQueueItem, EmailLog
from django.core.mail import send_mail

def check_email_health():
    """Check email system health and send alerts if needed"""
    failed_count = EmailQueueItem.objects.filter(status='failed').count()
    pending_count = EmailQueueItem.objects.filter(status='pending').count()
    
    if failed_count > 100:
        send_alert(f"WARNING: {failed_count} failed emails in queue")
    
    if pending_count > 1000:
        send_alert(f"WARNING: {pending_count} pending emails (possible backup)")
```

---

## Monitoring Dashboard

Create admin view for email stats:

```python
# movies/admin.py - Add to admin site

from django.contrib.admin import AdminSite
from movies.email import get_email_delivery_stats

class BookmyseatAdminSite(AdminSite):
    def index(self, request, extra_context=None):
        stats = get_email_delivery_stats()
        extra_context = extra_context or {}
        extra_context['email_stats'] = stats
        return super().index(request, extra_context)
```

---

## Maintenance Tasks

### Daily Tasks

```bash
# Check email queue size
python manage.py shell -c "
from movies.models import EmailQueueItem
print(f'Pending: {EmailQueueItem.objects.filter(status=\"pending\").count()}')
print(f'Failed: {EmailQueueItem.objects.filter(status=\"failed\").count()}')
"

# Check for errors in logs
grep ERROR logs/email_errors.log | tail -20
```

### Weekly Tasks

```bash
# Cleanup old logs (older than 30 days)
find logs -name "*.log" -mtime +30 -delete

# Cleanup old database logs (older than 90 days)
python manage.py shell -c "
from movies.models import EmailLog
from django.utils import timezone
from datetime import timedelta

cutoff = timezone.now() - timedelta(days=90)
deleted = EmailLog.objects.filter(created_at__lt=cutoff).delete()
print(f'Deleted {deleted[0]} old logs')
"

# Generate email delivery report
python manage.py shell << 'EOF'
from movies.models import EmailQueueItem
from django.db.models import Count

stats = EmailQueueItem.objects.values('status').annotate(count=Count('id'))
for stat in stats:
    print(f"{stat['status']}: {stat['count']}")
EOF
```

### Monthly Tasks

```bash
# Backup database
python manage.py dumpdata --exclude auth.permission --exclude contenttypes \
    > backups/db_$(date +%Y%m%d_%H%M%S).json

# Analyze email delivery patterns
python manage.py shell << 'EOF'
from movies.models import EmailLog
from django.db.models import Count

failures = EmailLog.objects.filter(
    status='failed'
).values('error_message').annotate(count=Count('id')).order_by('-count')[:5]

print("Top 5 failure reasons:")
for failure in failures:
    print(f"  {failure['error_message'][:80]}: {failure['count']}")
EOF

# Optimize database
python manage.py shell -c "
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute('ANALYZE')
"
```

---

## Troubleshooting

### Check Email Queue Status

```bash
python manage.py shell
from movies.models import EmailQueueItem
from movies.email import get_email_delivery_stats

# Overall stats
stats = get_email_delivery_stats()
print(f"Total: {stats['total']}, Sent: {stats['sent']}, Failed: {stats['failed']}")

# Detailed view
tasks = EmailQueueItem.objects.values('status').annotate(
    count=Count('id'),
    avg_attempts=Avg('attempts')
)
for task in tasks:
    print(f"{task['status']}: {task['count']} emails, avg attempts: {task['avg_attempts']}")
```

### View Recent Errors

```bash
grep -E "(ERROR|CRITICAL)" logs/email_errors.log | tail -50
```

### Manually Retry Failed Emails

```bash
# Via shell
python manage.py shell
from movies.models import EmailQueueItem
from django.utils import timezone

failed = EmailQueueItem.objects.filter(status='failed')
failed.update(
    status='pending',
    attempts=0,
    next_attempt_at=timezone.now()
)
print(f"Reset {failed.count()} emails for retry")

# Via Django command
python manage.py process_email_queue --status all --force-retry --limit 100
```

### Force Process Queue

```bash
# Process immediately without checking next_attempt_at
python manage.py process_email_queue --force-retry --limit 50

# Process specific status
python manage.py process_email_queue --status all --limit 100
```

---

## Performance Tuning

### Increase Processing Rate

```bash
# Increase limit per run
python manage.py process_email_queue --limit 200

# Increase cron frequency
*/1 * * * * python manage.py process_email_queue --limit 100  # Every minute
```

### Database Optimization

```python
# In settings.py
DATABASES['default']['CONN_MAX_AGE'] = 600  # Connection pooling

# Add database connection pooling package
# pip install psycopg2-pool
```

### Use Async Task Queue

For very high volume, use Celery:

```bash
pip install celery redis
```

```python
# tasks.py
from celery import shared_task
from django.core.management import call_command

@shared_task
def process_email_queue():
    call_command('process_email_queue', limit=100)

# Schedule with Celery Beat
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'process-email-queue': {
        'task': 'tasks.process_email_queue',
        'schedule': crontab(minute='*/5'),
    },
}
```

---

## Disaster Recovery

### Email Queue Backup

```bash
# Export email queue
python manage.py dumpdata movies.EmailQueueItem \
    > backups/email_queue_$(date +%Y%m%d).json

# Export email logs
python manage.py dumpdata movies.EmailLog \
    > backups/email_logs_$(date +%Y%m%d).json
```

### Restore From Backup

```bash
# Restore queue
python manage.py loaddata backups/email_queue_20240101.json

# Restore logs
python manage.py loaddata backups/email_logs_20240101.json
```

### Database Disaster Recovery

```bash
# Full database backup with compression
pg_dump bookmyseat | gzip > backups/db_$(date +%Y%m%d_%H%M%S).sql.gz

# Restore
gunzip -c backups/db_20240101_120000.sql.gz | psql bookmyseat
```

---

## Security Hardening

### Email Security

```python
# settings.py

# Rate limit SMTP connections
EMAIL_TIMEOUT = 10

# Use secure connection
EMAIL_USE_TLS = True
EMAIL_PORT = 587

# Set secure headers
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

### Admin Security

```python
# Restrict admin to HTTPS only
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    
# Rate limit admin logins
ADMIN_LOGIN_ATTEMPTS_LIMIT = 5
ADMIN_LOGIN_ATTEMPTS_WINDOW = 300  # 5 minutes
```

### Log Security

```bash
# Set restrictive permissions on logs
chmod 640 logs/*.log

# Rotate logs to prevent disk fill
# Use logrotate with maxage and maxsize
```

---

## Scaling Considerations

### As Volume Grows

**Small (< 1000 emails/day)**:
- Single process cron job
- SQLite database
- Simple file-based logs

**Medium (1000-10000 emails/day)**:
- Increase cron frequency
- Switch to PostgreSQL
- Add log rotation
- Monitor queue size daily

**Large (10000+ emails/day)**:
- Use task queue (Celery + Redis)
- Dedicated email service (SendGrid, AWS SES)
- Database clustering
- Separate email processing worker
- Webhook integration for delivery tracking

### Database Indexing

```python
# Indexes are created by migration for:
# - (status, next_attempt_at) - Fast pending query
# - (user, created_at) - User history
# - (to_email) - Recipient lookup
# - (status, created_at) - Status reporting
```

---

## References & Resources

- Email System Docs: [EMAIL_SYSTEM.md](EMAIL_SYSTEM.md)
- Integration Guide: [EMAIL_INTEGRATION_GUIDE.md](EMAIL_INTEGRATION_GUIDE.md)
- Django Documentation: https://docs.djangoproject.com/
- Celery Documentation: https://docs.celeryproject.org/
- Email Security: https://cheatsheetseries.owasp.org/cheatsheets/Email_Security_Cheat_Sheet.html
