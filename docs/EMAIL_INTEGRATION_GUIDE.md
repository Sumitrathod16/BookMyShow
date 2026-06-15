# Email Confirmation System - Integration Guide

## Quick Start

### 1. Setup (5 minutes)

**Step 1: Run migrations**
```bash
python manage.py migrate
```

This creates:
- `EmailQueueItem` table for email queue
- `EmailLog` table for delivery tracking
- Database indexes for performance

**Step 2: Configure email settings**

Create `.env` file in project root:
```bash
# Development (Console backend)
USE_SMTP_EMAIL=False

# Production (Gmail example)
USE_SMTP_EMAIL=True
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
```

**Step 3: Schedule email processing**

Add cron job (Linux/Mac):
```bash
# /etc/cron.d/bookmyseat
*/5 * * * * cd /path/to/bookmyseat && python manage.py process_email_queue --limit 50 >> /var/log/bookmyseat-email.log 2>&1
```

Or Windows Task Scheduler:
```
Program: C:\Python\python.exe
Arguments: manage.py process_email_queue --limit 50
Frequency: Every 5 minutes
```

---

## Implementation in Views

### Update book_seats() view to queue confirmation emails

**Current code** (in `movies/views.py`):
```python
@login_required(login_url='/login/')
def book_seats(request, theater_id):
    theater = get_object_or_404(Theater, id=theater_id)
    if request.method == 'POST':
        selected_seats = request.POST.getlist('seats')
        
        booked_bookings = []
        payment_id = uuid.uuid4().hex.upper()
        
        for seat_id in selected_seats:
            seat = get_object_or_404(Seat, id=seat_id, theater=theater)
            if not seat.is_booked:
                booking = Booking.objects.create(
                    user=request.user,
                    seat=seat,
                    movie=theater.movie,
                    theater=theater,
                    payment_id=payment_id,
                )
                seat.is_booked = True
                seat.save(update_fields=['is_booked'])
                booked_bookings.append(booking)
        
        # ✅ ADD THIS: Queue confirmation email
        if booked_bookings:
            transaction.on_commit(
                lambda: enqueue_booking_confirmation_email(booked_bookings)
            )
        
        messages.success(request, f'Booked {len(booked_bookings)} seat(s)...')
        return redirect('profile')
    
    seats = Seat.objects.filter(theater=theater)
    return render(request, 'movies/seat_selection.html', context)
```

**Key points**:
- `transaction.on_commit()` ensures email queued after booking saved
- Email is queued asynchronously (doesn't block response)
- User sees success message immediately
- Email sent in background via scheduled task

---

## Email Template Usage

### Template Variables Available

All variables passed to email templates (both HTML and plain text):

```python
{
    # User info
    'user_name': 'John Doe',
    'user_email': 'jo***@example.com',  # Masked for security
    
    # Movie info
    'movie_name': 'Inception',
    
    # Theater info
    'theater_name': 'PVR Cinema Downtown',
    
    # Show timing (in multiple formats)
    'show_date': 'December 15, 2024',
    'show_time': '2024-12-15T19:00:00Z',
    'show_time_formatted': '07:00 PM',
    
    # Booking details
    'seat_numbers': ['A1', 'A2', 'A3'],  # Sorted list
    'total_seats': 3,
    
    # Payment info
    'payment_id': '5a7e****1a2b',  # Masked for security
    
    # Timestamps
    'booking_time': '2024-12-15T14:30:00Z',
    'booking_time_formatted': 'December 15, 2024 at 02:30 PM',
    
    # Support
    'support_email': 'support@bookmyseat.com'
}
```

### Using Variables in Templates

**HTML Template**:
```html
<h1>Hello {{ user_name }}!</h1>
<p>Your movie: <strong>{{ movie_name }}</strong></p>
<p>Theater: {{ theater_name }}</p>
<p>Time: {{ show_time_formatted }}</p>
<p>Seats: {{ seat_numbers|join:", " }}</p>
<p>Reference: {{ payment_id }}</p>
```

**Plain Text Template**:
```
Hello {{ user_name }},

Movie: {{ movie_name }}
Theater: {{ theater_name }}
Time: {{ show_time_formatted }}
Seats: {{ seat_numbers|join:", " }}
Reference: {{ payment_id }}
```

### Custom Filters

Django template filters available:
```html
<!-- Join seat list -->
{{ seat_numbers|join:", " }}  → "A1, A2, A3"

<!-- Format dates -->
{{ show_date|upper }}         → "DECEMBER 15, 2024"

<!-- Conditional rendering -->
{% if total_seats > 1 %}
  You booked {{ total_seats }} seats.
{% else %}
  You booked 1 seat.
{% endif %}
```

---

## Monitoring & Management

### View Queue Status (Django Shell)

```bash
python manage.py shell
```

```python
from movies.models import EmailQueueItem, EmailLog
from movies.email import get_email_delivery_stats

# Get stats
stats = get_email_delivery_stats()
print(f"Sent: {stats['sent']}, Failed: {stats['failed']}, Pending: {stats['pending']}")

# View pending emails
EmailQueueItem.objects.filter(status='pending').count()

# View recent failures
failures = EmailLog.objects.filter(status='failed').order_by('-created_at')[:10]
for log in failures:
    print(f"User: {log.user}, Error: {log.error_message}")

# Retry specific email
task = EmailQueueItem.objects.get(pk=123)
task.status = 'pending'
task.attempts = 0
task.next_attempt_at = timezone.now()
task.save()
```

### Admin Dashboard Actions

1. **View email queue**: Django Admin → Movies → Email Queue Items
2. **Filter by status**: Click Status filter → Select "Pending", "Sent", or "Failed"
3. **Retry failed emails**:
   - Filter by Status = Failed
   - Check checkboxes for emails to retry
   - Select "Retry selected emails"
   - Click "Go"
4. **View delivery logs**: Django Admin → Movies → Email Logs
5. **Search by email**: Use search box to find specific email

### Logs

**Check email logs**:
```bash
# View live email processing
tail -f logs/email.log

# View only errors
grep ERROR logs/email_errors.log

# View specific user's emails
grep "user_id=123" logs/email.log
```

---

## Testing & Debugging

### Test Email in Development

**Step 1: Queue test email**
```bash
python manage.py shell
from django.contrib.auth.models import User
from movies.models import Booking, EmailQueueItem
from movies.email import enqueue_booking_confirmation_email

user = User.objects.get(username='testuser')
booking = Booking.objects.filter(user=user).first()
email_queue = enqueue_booking_confirmation_email([booking])
print(f"Queued: {email_queue}")
```

**Step 2: Process queue (Console backend)**
```bash
python manage.py process_email_queue --limit 1
```

Output (prints to console):
```
Subject: Your Booking Confirmation: Inception
From: noreply@bookmyseat.com
To: test@example.com

Hello John Doe,
Your booking confirmation details...
```

### Test Email in Production

**Step 1: Verify SMTP settings**
```python
python manage.py shell
from django.core.mail import send_mail

result = send_mail(
    'Test Email',
    'This is a test.',
    'noreply@bookmyseat.com',
    ['your-email@example.com'],
    fail_silently=False,
)
print(f"Sent: {result} emails")
```

**Step 2: Process queue**
```bash
python manage.py process_email_queue --limit 1
```

Check inbox for confirmation email.

### Debug Failed Email

```python
python manage.py shell
from movies.models import EmailQueueItem, EmailLog

# Find the failed email
task = EmailQueueItem.objects.get(pk=123)
print(f"Status: {task.status}")
print(f"Attempts: {task.attempts}/{task.max_attempts}")
print(f"Last Error: {task.last_error}")
print(f"Next Attempt: {task.next_attempt_at}")

# View all events for this email
logs = EmailLog.objects.filter(email_queue_item=task).order_by('-created_at')
for log in logs:
    print(f"{log.created_at} - {log.status} - {log.message}")
    if log.error_message:
        print(f"  Error: {log.error_message}")
```

---

## Security Best Practices

### Masking Sensitive Data

All sensitive data is automatically masked in logs:

```
# Emails masked in logs
Original: john.doe@example.com
Logged as: jo***@example.com

# Payment IDs masked in templates
Original: PAY5a7e8f1a2b3c4d5e
Shown as: PAY5****1a2b

# Database: Full data stored (access controlled)
Templates: Masked data shown to users
Logs: Sensitive data masked
```

### Environment Variables

**Never commit credentials to Git**:
```bash
# ✅ GOOD: Use .env file
cat .env.example  # Track this
cat .env         # DON'T track this

# ✅ Add to .gitignore
echo ".env" >> .gitignore
```

### SMTP Security

**Always use TLS/SSL**:
```python
# ✅ CORRECT: Use TLS
EMAIL_PORT = 587
EMAIL_USE_TLS = True

# ✅ ALSO CORRECT: Use SSL
EMAIL_PORT = 465
EMAIL_USE_SSL = True

# ❌ WRONG: No encryption
EMAIL_PORT = 25
EMAIL_USE_TLS = False
```

### Database Access

**Restrict admin access**:
```python
# Django admin: Only authenticated superusers can access
# Add permission checks in production
# Consider 2FA for admin accounts
```

---

## Performance Optimization

### Batch Processing

**Process multiple emails per run**:
```bash
# Process 100 emails instead of default 20
python manage.py process_email_queue --limit 100
```

**Increase cron frequency**:
```bash
# Run every minute for faster delivery
* * * * * cd /path/to/bookmyseat && python manage.py process_email_queue --limit 100
```

### Database Queries

**Emails sent efficiently**:
```python
# ✅ Good: select_related() prevents N+1 queries
tasks = EmailQueueItem.objects.select_related('user').filter(
    status='pending'
)[:50]

# ❌ Bad: N+1 queries
for task in tasks:
    print(task.user.username)  # Extra query each time
```

### Cache Email Stats

```python
from django.core.cache import cache
from movies.email import get_email_delivery_stats

# Cache stats for 5 minutes
stats = cache.get_or_set(
    'email_stats',
    get_email_delivery_stats,
    timeout=300
)
```

---

## Troubleshooting

### Common Issues

**Q: Emails not sending**
```
A: Debug steps:
   1. Check USE_SMTP_EMAIL=True in settings
   2. Verify credentials are correct
   3. Run: python manage.py test_email
   4. Check logs: tail -f logs/email.log
```

**Q: "Connection refused" error**
```
A: Common causes:
   1. SMTP server down or wrong host
   2. Wrong port number
   3. Firewall blocking connection
   4. Use telnet to test: telnet smtp.gmail.com 587
```

**Q: "Authentication failed"**
```
A: Common causes:
   1. Wrong username/password
   2. Need to use app-specific password (Gmail)
   3. SMTP server auth method not supported
   4. Special characters in password not escaped
```

**Q: Emails stuck in PENDING**
```
A: Debug steps:
   1. Check cron job is running: ps aux | grep process_email_queue
   2. Check logs for errors: tail -f logs/email.log
   3. Manually process: python manage.py process_email_queue --force-retry
   4. Check database: EmailQueueItem.objects.filter(status='pending').count()
```

**Q: Too many failed emails**
```
A: Reasons and solutions:
   1. SMTP rate limits → Increase delays or upgrade plan
   2. Invalid emails → Validate before queueing
   3. Server timeouts → Increase EMAIL_TIMEOUT
   4. Disk space → Check server resources
```

### Error Messages

**"Email task has no recipient"**
```
Cause: to_email field is empty or null
Fix: Check user.email is set before queuing
```

**"Expected to send 1 email, sent X"**
```
Cause: SMTP connection issue or duplicate sends
Fix: Check EMAIL_BACKEND setting and SMTP server status
```

**"Connection timeout"**
```
Cause: SMTP server not responding
Fix: 
  1. Increase EMAIL_TIMEOUT in settings
  2. Check SMTP server is running
  3. Check network connectivity
```

---

## API Reference

### enqueue_booking_confirmation_email()

```python
def enqueue_booking_confirmation_email(
    bookings: List[Booking]
) -> Optional[EmailQueueItem]
```

**Parameters**:
- `bookings` - List of Booking objects

**Returns**:
- EmailQueueItem if queued
- None if skipped

**Example**:
```python
from movies.email import enqueue_booking_confirmation_email
from django.db import transaction

bookings = [booking1, booking2, booking3]
transaction.on_commit(
    lambda: enqueue_booking_confirmation_email(bookings)
)
```

### send_email_task()

```python
def send_email_task(task: EmailQueueItem) -> bool
```

**Parameters**:
- `task` - EmailQueueItem to send

**Returns**:
- True on success
- Raises exception on failure

**Example**:
```python
from movies.email import send_email_task
from movies.models import EmailQueueItem

task = EmailQueueItem.objects.get(pk=123)
try:
    send_email_task(task)
except Exception as e:
    print(f"Send failed: {e}")
```

### log_email_event()

```python
def log_email_event(
    task: Optional[EmailQueueItem],
    user,
    status: str,
    message: str = '',
    error_message: str = '',
    log_level: str = 'INFO',
    details: Optional[Dict] = None,
) -> EmailLog
```

**Example**:
```python
from movies.email import log_email_event
from movies.models import EmailLog

log_email_event(
    task=email_queue_item,
    user=user,
    status=EmailLog.Status.SENT,
    message='Email delivered',
    log_level=EmailLog.LogLevel.INFO,
)
```

### get_email_delivery_stats()

```python
def get_email_delivery_stats() -> Dict[str, Any]
```

**Returns**:
```python
{
    'total': 1250,
    'sent': 1200,
    'failed': 30,
    'pending': 20,
    'success_rate': 96.0
}
```

**Example**:
```python
from movies.email import get_email_delivery_stats

stats = get_email_delivery_stats()
print(f"Email success rate: {stats['success_rate']}%")
```

---

## FAQ

**Q: Do emails block the booking response?**
A: No! Emails are queued asynchronously. The booking API returns immediately, and emails are sent in the background via the scheduled management command.

**Q: How many times will an email be retried?**
A: By default, 5 times. Configurable via `EMAIL_MAX_ATTEMPTS` setting.

**Q: What happens if an email fails 5 times?**
A: It's marked as FAILED and stored in the database. You can retry it manually via the admin interface or set `next_attempt_at` and change status back to PENDING.

**Q: Can I send custom emails?**
A: Yes. Create a new template and use `enqueue_booking_confirmation_email()` with custom `template_name` and `payload`.

**Q: How do I change the email template?**
A: Edit `templates/emails/booking_confirmation.html` and/or `templates/emails/booking_confirmation.txt`.

**Q: Can I track if a user opened the email?**
A: Not by default. Use a transactional email service (SendGrid, AWS SES, Mailgun) with webhook integration to track opens/clicks.

**Q: Is the payment ID visible in emails?**
A: The payment ID is masked in logs and templates for security. Only the first 4 and last 4 characters are shown.

---

## Support & Resources

- Documentation: [docs/EMAIL_SYSTEM.md](EMAIL_SYSTEM.md)
- Django Email Docs: https://docs.djangoproject.com/en/stable/topics/email/
- Email Security: https://owasp.org/www-community/attacks/Email_Injection
- SMTP Providers: Gmail, SendGrid, AWS SES, Mailgun
