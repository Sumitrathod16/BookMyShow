# Email Confirmation System - Technical Documentation

## Overview

This document describes the comprehensive automated ticket email confirmation system with template engine, retry logic, and monitoring capabilities.

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         Booking API                              │
└──────────────────────────┬──────────────────────────────────────┘
                           │ (Non-blocking)
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│           transaction.on_commit() Hook                           │
│    (Fires after booking committed to database)                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│    enqueue_booking_confirmation_email()                         │
│    - Builds email context with booking details                 │
│    - Masks sensitive data for logging                          │
│    - Creates EmailQueueItem record                             │
│    - Returns immediately (non-blocking)                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│         EmailQueueItem Database Record                          │
│  (Status: PENDING, ready for asynchronous delivery)            │
└──────────────────────────┬──────────────────────────────────────┘
                           │ (Via management command or background job)
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│       process_email_queue Management Command                    │
│ - Fetches pending emails                                        │
│ - Renders templates (HTML + plain text)                        │
│ - Sends via configured SMTP backend                            │
│ - Implements exponential backoff retry logic                   │
│ - Logs all events with structured data                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                    ┌──────┴──────┐
                    ↓             ↓
        ┌──────────────────┐  ┌──────────────────┐
        │  Email Sent ✓    │  │  Email Failed ✗  │
        │  (SENT status)   │  │  (PENDING/FAILED) │
        │  Logged in DB    │  │  Scheduled retry │
        └──────────────────┘  └──────────────────┘
```

### Key Features

1. **Non-Blocking Operations**: Email queue jobs don't block booking API responses
2. **Template Engine**: Django template system with context masking
3. **Retry Logic**: Exponential backoff with configurable max attempts
4. **Security**: Sensitive data masking in logs (emails, payment IDs)
5. **Monitoring**: Comprehensive logging and email delivery tracking
6. **Admin Interface**: Beautiful Django admin for queue management
7. **Multi-Format**: HTML and plain text email templates

---

## Models

### EmailQueueItem

Represents an email waiting to be sent or already sent.

```python
class EmailQueueItem(models.Model):
    # Recipient information
    user = ForeignKey(User)              # Booking user
    to_email = EmailField()              # Destination email
    
    # Content
    subject = CharField()                # Email subject
    template_name = CharField()          # Template path (e.g., 'emails/booking_confirmation.html')
    payload = JSONField()                # Template context data
    
    # Delivery tracking
    status = CharField()                 # PENDING, SENT, FAILED
    attempts = PositiveSmallIntegerField(default=0)
    max_attempts = PositiveSmallIntegerField(default=5)
    
    # Error handling
    last_error = TextField()             # Last error message
    next_attempt_at = DateTimeField()    # Next retry time (exponential backoff)
    sent_at = DateTimeField()            # When email was successfully sent
    
    # Metadata
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
```

**Indexes**: For optimal query performance
- `(status, next_attempt_at)` - For fetching pending emails
- `(user, created_at)` - For user email history
- `(to_email)` - For finding emails by recipient

### EmailLog

Detailed audit trail of email delivery events.

```python
class EmailLog(models.Model):
    # Association
    email_queue_item = ForeignKey(EmailQueueItem, null=True)
    user = ForeignKey(User)
    email_address = EmailField()
    
    # Event details
    status = CharField()                 # QUEUED, SENDING, SENT, DELIVERED, FAILED, BOUNCED, COMPLAINED
    message = TextField()                # Human-readable message
    error_message = TextField()          # Error details if applicable
    log_level = CharField()              # DEBUG, INFO, WARNING, ERROR, CRITICAL
    details = JSONField()                # Structured data (e.g., retry delay, attempt count)
    
    # Metadata
    created_at = DateTimeField(auto_now_add=True)
```

**Use Cases**:
- Track delivery status per email
- Analyze failure patterns
- Generate delivery reports
- Debug customer email issues

---

## API Functions

### enqueue_booking_confirmation_email()

**Purpose**: Queue a booking confirmation email for asynchronous delivery.

**Signature**:
```python
def enqueue_booking_confirmation_email(bookings: List[Booking]) -> Optional[EmailQueueItem]
```

**Parameters**:
- `bookings` (List[Booking]): Bookings for the same user/show (can be multiple seats)

**Returns**:
- EmailQueueItem if successfully queued
- None if email queued skipped (e.g., no user email)

**Example Usage** (in views.py):
```python
from django.db import transaction
from movies.email import enqueue_booking_confirmation_email

@login_required
def book_seats(request, theater_id):
    # ... booking logic ...
    
    booked_bookings = []
    for seat_id in selected_seats:
        # Create booking...
        booking = Booking.objects.create(...)
        booked_bookings.append(booking)
    
    # Queue email after transaction commits (non-blocking)
    if booked_bookings:
        transaction.on_commit(lambda: enqueue_booking_confirmation_email(booked_bookings))
    
    # Response returns immediately, email queued asynchronously
    return redirect('profile')
```

**Context Data Provided to Template**:
```python
{
    'user_name': 'John Doe',
    'user_email': 'jo***@example.com',  # Masked for security
    'movie_name': 'Inception',
    'theater_name': 'PVR Cinema',
    'show_date': 'December 15, 2024',
    'show_time': '2024-12-15T19:00:00Z',
    'show_time_formatted': '07:00 PM',
    'seat_numbers': ['A1', 'A2', 'A3'],
    'payment_id': '5a7e****1a2b',  # Masked for security
    'total_seats': 3,
    'booking_time': '2024-12-15T14:30:00Z',
    'booking_time_formatted': 'December 15, 2024 at 02:30 PM',
    'support_email': 'support@bookmyseat.com'
}
```

---

### send_email_task()

**Purpose**: Send an email from the queue (called by management command).

**Signature**:
```python
def send_email_task(task: EmailQueueItem) -> bool
```

**Parameters**:
- `task` (EmailQueueItem): Queue item to send

**Returns**:
- True on success
- Raises exception on failure

**Internal Process**:
1. Validates recipient email
2. Renders HTML template
3. Renders text template (fallback to stripped HTML)
4. Creates EmailMultiAlternatives message
5. Sends via configured SMTP backend
6. Returns True on success

**Example** (internal usage in process_email_queue.py):
```python
for task in pending_tasks:
    try:
        send_email_task(task)
        task.status = EmailQueueItem.Status.SENT
        task.sent_at = timezone.now()
        task.save()
    except Exception as exc:
        # Retry logic...
```

---

### log_email_event()

**Purpose**: Log an email event for monitoring and debugging.

**Signature**:
```python
def log_email_event(
    task: Optional[EmailQueueItem],
    user,
    status: str,
    message: str = '',
    error_message: str = '',
    log_level: str = EmailLog.LogLevel.INFO,
    details: Optional[Dict] = None,
) -> EmailLog
```

**Parameters**:
- `task`: Associated EmailQueueItem (can be None)
- `user`: User object
- `status`: Email status (QUEUED, SENDING, SENT, FAILED, etc.)
- `message`: Human-readable message
- `error_message`: Error details
- `log_level`: Log level (INFO, WARNING, ERROR)
- `details`: Additional structured data

**Example**:
```python
log_email_event(
    task=email_queue_item,
    user=user,
    status=EmailLog.Status.SENT,
    message='Email delivered successfully',
    log_level=EmailLog.LogLevel.INFO,
    details={'delivery_time_ms': 1234},
)
```

---

### get_email_delivery_stats()

**Purpose**: Get email delivery statistics for monitoring dashboards.

**Signature**:
```python
def get_email_delivery_stats() -> Dict[str, Any]
```

**Returns**:
```python
{
    'total': 1250,          # Total emails in queue
    'sent': 1200,           # Successfully sent
    'failed': 30,           # Failed (max attempts exceeded)
    'pending': 20,          # Waiting to send
    'success_rate': 96.0    # Percentage
}
```

---

## Management Command

### process_email_queue

**Purpose**: Process pending emails with retry logic and exponential backoff.

**Location**: `movies/management/commands/process_email_queue.py`

**Usage**:
```bash
# Process 20 pending emails (default)
python manage.py process_email_queue

# Process 50 emails
python manage.py process_email_queue --limit 50

# Force retry of failed emails
python manage.py process_email_queue --force-retry

# Process all emails (pending + failed)
python manage.py process_email_queue --status all
```

**Options**:
- `--limit N`: Maximum emails to process (default: 20)
- `--force-retry`: Ignore next_attempt_at timing
- `--status [pending|all]`: Filter by status (default: pending)

**Retry Logic - Exponential Backoff**:
```
Attempt 1: Retry after 2^1 * 60 = 2 minutes
Attempt 2: Retry after 2^2 * 60 = 4 minutes
Attempt 3: Retry after 2^3 * 60 = 8 minutes
Attempt 4: Retry after 2^4 * 60 = 16 minutes
Attempt 5: Retry after 2^5 * 60 = 32 minutes
Max cap: 3600 seconds (1 hour)

After max_attempts (default: 5), email marked as FAILED
```

**Output Example**:
```
Processing 3 email task(s)...

[1/3] Sending email to jo***@example.com... ✓ SENT
[2/3] Sending email to sa***@example.com... ✓ SENT
[3/3] Sending email to m***@example.com... ✗ FAILED (Retry 2/5 in 240s)

============================================================
✓ Successful: 2
✗ Failed: 1
============================================================
```

**Scheduling**:

**Option 1: Cron Job** (Unix/Linux/Mac)
```bash
# Process emails every 5 minutes
*/5 * * * * cd /path/to/bookmyseat && python manage.py process_email_queue --limit 50

# Process emails every minute during business hours
* 9-17 * * 1-5 cd /path/to/bookmyseat && python manage.py process_email_queue --limit 100
```

**Option 2: Celery Beat** (Background task queue)
```python
from celery.schedules import crontab
from celery.task import periodic_task

@periodic_task(run_every=crontab(minute='*/5'))
def process_email_queue_task():
    from django.core.management import call_command
    call_command('process_email_queue', limit=50)
```

**Option 3: APScheduler**
```python
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.add_job(
    lambda: call_command('process_email_queue'),
    'interval',
    minutes=5,
    id='process_email_queue',
)
scheduler.start()
```

---

## Email Configuration

### Environment Variables

```bash
# SMTP Configuration
USE_SMTP_EMAIL=True
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
EMAIL_TIMEOUT=10

# From and support emails
DEFAULT_FROM_EMAIL=noreply@bookmyseat.com
SUPPORT_EMAIL=support@bookmyseat.com

# Retry configuration
EMAIL_MAX_ATTEMPTS=5
EMAIL_RETRY_DELAY_MINUTES=1
```

### Django Settings

```python
# Email backend selection
USE_SMTP_EMAIL = os.getenv('USE_SMTP_EMAIL', 'False').lower() in ('1', 'true', 'yes')

# SMTP settings (if USE_SMTP_EMAIL is True)
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('1', 'true', 'yes')
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '10'))

# Retry settings
EMAIL_MAX_ATTEMPTS = int(os.getenv('EMAIL_MAX_ATTEMPTS', '5'))
```

### Email Providers

**Gmail**:
```
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-16-character-app-password
```

**SendGrid**:
```
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=SG.your-sendgrid-api-key
```

**AWS SES**:
```
EMAIL_HOST=email-smtp.us-east-1.amazonaws.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-ses-smtp-username
EMAIL_HOST_PASSWORD=your-ses-smtp-password
```

**Development (Console Backend)**:
```
USE_SMTP_EMAIL=False  # Uses console backend
# Emails printed to stdout
```

---

## Security Considerations

### Sensitive Data Masking

All sensitive data is masked in logs and email display:

```python
# Original email
user_email = "john.doe@example.com"
# Masked in logs
masked_email = "jo***@example.com"

# Original payment ID
payment_id = "PAY5a7e8f1a2b3c4d5e"
# Masked in logs and template
masked_payment_id = "PAY5****1a2b"
```

### Security Practices

1. **Environment Variables**: Credentials stored as env vars, not in code
2. **TLS/SSL**: Always use encrypted SMTP connections (port 587 with TLS)
3. **App Passwords**: Use app-specific passwords, not main passwords
4. **Logging**: Sensitive data automatically masked in logs
5. **Template Data**: Email templates show masked payment IDs
6. **Database**: Queue items stored with full emails (only readable by authorized users)
7. **CSRF Protection**: Django CSRF middleware protects booking API

### SSL/TLS Configuration

```python
# Always use TLS for production
EMAIL_USE_TLS = True          # Use STARTTLS (port 587)
# OR
EMAIL_USE_SSL = True          # Use implicit SSL (port 465)

# Timeout to prevent hanging connections
EMAIL_TIMEOUT = 10  # seconds
```

---

## Logging & Monitoring

### Log Files

**Location**: `logs/` directory in project root

```
logs/
├── django.log           # All Django logs
├── email.log            # Email system debug logs
└── email_errors.log     # Email errors and warnings
```

### Log Configuration

```python
LOGGING = {
    'loggers': {
        'movies.email': {
            'level': 'DEBUG',
            'handlers': ['console', 'email_file', 'email_errors'],
        },
        'movies.email.sensitive': {
            'level': 'WARNING',
            'handlers': ['null'],  # Don't log sensitive data
        },
    }
}
```

### Log Messages

**Successful Queue**:
```
[INFO] Queued booking confirmation email: user_id=123, email=jo***@example.com, seats=3, payment_id=PAY5****1a2b
```

**Successful Send**:
```
[INFO] Email sent successfully: task_id=456, email=jo***@example.com, subject=Your Booking Confirmation: Inception
```

**Failed Send with Retry**:
```
[WARNING] Email task 456 failed (attempt 2/5), retry scheduled in 240 seconds: Connection timeout
```

**Permanent Failure**:
```
[ERROR] Email task 456 failed permanently after 5 attempts: Invalid recipient address
```

### Querying Logs

```python
# In Django shell
python manage.py shell

from movies.models import EmailLog, EmailQueueItem

# Find all failed emails for a user
EmailLog.objects.filter(
    user__username='john_doe',
    status='failed'
).order_by('-created_at')

# Get delivery stats
EmailQueueItem.objects.filter(status='sent').count()

# Find emails with specific error
EmailLog.objects.filter(
    error_message__icontains='timeout'
).values('error_message').distinct()
```

---

## Admin Interface

### EmailQueueItem Admin

**Access**: Django Admin → Movies → Email Queue Items

**Features**:
- Color-coded status badges (Orange=Pending, Green=Sent, Red=Failed)
- Attempt counter with max attempts
- Error message display (first 500 chars)
- Payload viewer (JSON formatted)
- Actions: Mark Pending, Mark Failed, Retry Selected
- Filters: By status and date
- Search: By email, subject, or payment ID

**Example**: Retrying failed emails
1. Filter by Status = Failed
2. Select failed emails
3. Choose "Retry selected emails" action
4. Click "Go"

### EmailLog Admin

**Access**: Django Admin → Movies → Email Logs

**Features**:
- Event status badges with color coding
- Log level indicators
- Email address display (masked)
- User and timestamp information
- Error message viewer
- Structured details in JSON format
- Filters: By status, log level, and date
- Search: By email, username, or message

---

## Testing

### Manual Testing

**1. Test Email Queue**:
```bash
# Create a test booking
python manage.py shell
from django.contrib.auth.models import User
from movies.models import Movie, Theater, Seat, Booking, EmailQueueItem
from movies.email import enqueue_booking_confirmation_email

user = User.objects.first()
booking = Booking.objects.first()

# Queue email
email_queue = enqueue_booking_confirmation_email([booking])
print(f"Queued: {email_queue}")

# View pending emails
EmailQueueItem.objects.filter(status='pending').count()
```

**2. Process Queue (Development - Console Backend)**:
```bash
python manage.py process_email_queue --limit 1
```

Output (console backend prints email content):
```
Subject: Your Booking Confirmation: Inception
From: noreply@bookmyseat.com
To: john@example.com

Content-Type: text/plain; charset="utf-8"
MIME-Version: 1.0
Content-Transfer-Encoding: 7bit

[Email body...]
```

**3. Production Testing (SMTP)**:
```bash
# Set env vars
export USE_SMTP_EMAIL=True
export EMAIL_HOST_USER=your@gmail.com
export EMAIL_HOST_PASSWORD=your-app-password

# Process queue
python manage.py process_email_queue --limit 1
```

### Automated Testing

```python
# movies/tests_email.py
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from movies.models import Movie, Theater, Seat, Booking, EmailQueueItem, EmailLog
from movies.email import (
    enqueue_booking_confirmation_email,
    send_email_task,
    mask_email,
    mask_payment_id,
)

class EmailQueueTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'pass123')
        self.movie = Movie.objects.create(name='Test Movie', rating=8.5, cast='Test Cast')
        self.theater = Theater.objects.create(
            name='Test Theater',
            movie=self.movie,
            time=timezone.now()
        )
        self.seat = Seat.objects.create(
            theater=self.theater,
            seat_number='A1',
            is_booked=True
        )

    def test_enqueue_booking_confirmation_email(self):
        """Test email queueing"""
        booking = Booking.objects.create(
            user=self.user,
            seat=self.seat,
            movie=self.movie,
            theater=self.theater,
            payment_id='TEST123'
        )
        
        queue_item = enqueue_booking_confirmation_email([booking])
        
        self.assertIsNotNone(queue_item)
        self.assertEqual(queue_item.status, EmailQueueItem.Status.PENDING)
        self.assertEqual(queue_item.to_email, 'test@example.com')

    def test_mask_email(self):
        """Test email masking"""
        email = "john.doe@example.com"
        masked = mask_email(email)
        self.assertEqual(masked, "jo***@example.com")

    def test_mask_payment_id(self):
        """Test payment ID masking"""
        payment_id = "PAY5a7e8f1a2b3c4d5e"
        masked = mask_payment_id(payment_id)
        self.assertEqual(masked, "PAY5****1a2b")

    def test_send_email_task_without_recipient(self):
        """Test error handling for missing recipient"""
        queue_item = EmailQueueItem.objects.create(
            user=self.user,
            to_email='',
            subject='Test',
            template_name='emails/booking_confirmation.html',
            payload={}
        )
        
        with self.assertRaises(ValueError):
            send_email_task(queue_item)
```

---

## Troubleshooting

### Common Issues

**Issue**: "Email not sending"
```
Debug steps:
1. Check USE_SMTP_EMAIL=True in settings
2. Verify env vars: EMAIL_HOST_USER, EMAIL_HOST_PASSWORD
3. Check email logs: tail -f logs/email.log
4. Test SMTP connection: python manage.py shell
   from django.core.mail import send_mail
   send_mail('Test', 'Body', 'from@example.com', ['to@example.com'])
```

**Issue**: "Connection timeout"
```
Debug steps:
1. Increase EMAIL_TIMEOUT: EMAIL_TIMEOUT=30
2. Check firewall/network connectivity
3. Verify EMAIL_PORT matches protocol:
   - 587 for TLS
   - 465 for SSL
   - 25 for unencrypted
4. Check SMTP server status
```

**Issue**: "Authentication failed"
```
Debug steps:
1. Verify EMAIL_HOST_USER is correct
2. Check PASSWORD is app-specific (not main password)
3. Verify SMTP server allows this auth method
4. Check for special characters in password (escape if needed)
```

**Issue**: "Emails stuck in PENDING"
```
Debug steps:
1. Check management command is running:
   ps aux | grep process_email_queue
2. Check cron logs (if using cron):
   grep CRON /var/log/syslog
3. Manually process queue:
   python manage.py process_email_queue --limit 1 --force-retry
4. Check database for errors:
   EmailQueueItem.objects.filter(status='pending').values('last_error').distinct()
```

**Issue**: "Emails marked as FAILED too quickly"
```
Debug steps:
1. Check EMAIL_MAX_ATTEMPTS setting
2. Increase retry delays: EMAIL_RETRY_DELAY_MINUTES
3. Review error messages in email_errors.log
4. Check SMTP provider rate limits
```

---

## Performance Optimization

### Database Optimization

**Indexes**: Automatically created by migration
```python
# Indexes for queries
(status, next_attempt_at)    # Fetch pending emails
(user, created_at)           # User email history
(to_email)                   # Find by recipient
```

### Query Optimization

```python
# Good: Use select_related for ForeignKeys
tasks = EmailQueueItem.objects.select_related('user').filter(
    status='pending',
    next_attempt_at__lte=now
)[:50]

# Bad: N+1 query problem
for task in tasks:
    print(task.user.username)  # Extra query per item
```

### Batch Processing

```bash
# Process multiple emails per run
python manage.py process_email_queue --limit 100

# Schedule frequent runs
*/1 * * * * python manage.py process_email_queue --limit 50
```

### Database Connection Pooling

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'CONN_MAX_AGE': 600,  # Connection timeout
        # Add psycopg2 pool settings if needed
    }
}
```

---

## Deployment Checklist

- [ ] Set environment variables (EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, etc.)
- [ ] Run migrations: `python manage.py migrate`
- [ ] Create logs directory: `mkdir -p logs`
- [ ] Test SMTP configuration
- [ ] Set up cron job or background task scheduler
- [ ] Configure log rotation (logrotate or similar)
- [ ] Test email delivery end-to-end
- [ ] Monitor email logs daily
- [ ] Set up alerts for failed emails
- [ ] Document recovery procedures
- [ ] Backup database regularly
- [ ] Review and mask sensitive data in logs

---

## References

- [Django Email Documentation](https://docs.djangoproject.com/en/stable/topics/email/)
- [Django Templates](https://docs.djangoproject.com/en/stable/topics/templates/)
- [Django Management Commands](https://docs.djangoproject.com/en/stable/howto/custom-management-commands/)
- [SMTP Protocol Specification](https://tools.ietf.org/html/rfc5321)
- [Email Security Best Practices](https://cheatsheetseries.owasp.org/cheatsheets/Email_Security_Cheat_Sheet.html)
