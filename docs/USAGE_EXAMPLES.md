# Email System - Usage Examples

## Example 1: Basic Setup

### Step 1: Initialize
```bash
cd /path/to/BookMyShow

# Run migrations
python manage.py migrate

# Create logs directory
mkdir -p logs

# Copy environment template
cp .env.example .env
```

### Step 2: Configure Email (in .env)
```bash
# Development (console backend - emails print to console)
USE_SMTP_EMAIL=False

# Production (Gmail example)
USE_SMTP_EMAIL=True
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-16-char-app-password
```

### Step 3: Test Queue
```bash
python manage.py shell
from movies.models import Booking
from movies.email import enqueue_booking_confirmation_email

booking = Booking.objects.first()
email_queue = enqueue_booking_confirmation_email([booking])
print(f"Queued: {email_queue}")
```

### Step 4: Process Queue (Development)
```bash
# With console backend, emails print to console
python manage.py process_email_queue --limit 1
```

Output:
```
Subject: Your Booking Confirmation: Inception
From: noreply@bookmyseat.com
To: user@example.com

[Email content with all booking details...]
```

---

## Example 2: Integration in Views

### Before (in movies/views.py)
```python
@login_required
def book_seats(request, theater_id):
    # ... booking logic ...
    
    if booked_bookings:
        # OLD: No email notification
        messages.success(request, f'Booked {len(booked_bookings)} seat(s)...')
    
    return redirect('profile')
```

### After (with email)
```python
from django.db import transaction
from movies.email import enqueue_booking_confirmation_email

@login_required
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
                seat.save()
                booked_bookings.append(booking)
        
        # ✅ NEW: Queue confirmation email (non-blocking)
        if booked_bookings:
            transaction.on_commit(
                lambda: enqueue_booking_confirmation_email(booked_bookings)
            )
        
        messages.success(request, f'Booked {len(booked_bookings)} seat(s)! Confirmation email sent.')
        return redirect('profile')
    
    return render(request, 'movies/seat_selection.html', context)
```

**Key Changes**:
- `transaction.on_commit()` ensures email queued after booking saved
- Email queued asynchronously (doesn't block response)
- User sees success message immediately
- Email sent in background

---

## Example 3: Monitoring Email Queue

### Check Queue Status
```bash
python manage.py shell
from movies.models import EmailQueueItem, EmailLog
from movies.email import get_email_delivery_stats

# Get overall stats
stats = get_email_delivery_stats()
print(f"""
Email Delivery Stats:
  Total: {stats['total']}
  Sent: {stats['sent']}
  Failed: {stats['failed']}
  Pending: {stats['pending']}
  Success Rate: {stats['success_rate']}%
""")

# View pending emails
pending = EmailQueueItem.objects.filter(status='pending')
print(f"Pending emails: {pending.count()}")
for email in pending[:5]:
    print(f"  - {email.to_email}: {email.subject}")

# View recent failures
failures = EmailLog.objects.filter(status='failed').order_by('-created_at')[:5]
print(f"\nRecent failures:")
for log in failures:
    print(f"  - {log.email_address}: {log.error_message[:80]}")
```

### View Admin Dashboard
```bash
python manage.py runserver
# Navigate to: http://localhost:8000/admin/movies/
# Click on "Email Queue Items" or "Email Logs"
```

---

## Example 4: Processing Queue Manually

### Development (Process 1 email with console backend)
```bash
USE_SMTP_EMAIL=False python manage.py process_email_queue --limit 1
```

Output:
```
Processing 1 email task(s)...

[1/1] Sending email to user@example.com... ✓ SENT

============================================================
✓ Successful: 1
============================================================
```

### Production (Process 50 emails with SMTP)
```bash
python manage.py process_email_queue --limit 50
```

### Force Retry Failed Emails
```bash
python manage.py process_email_queue --force-retry --limit 100
```

### Process All Emails (Pending + Failed)
```bash
python manage.py process_email_queue --status all --limit 100
```

---

## Example 5: Scheduled Processing (Cron)

### Setup Cron Job (every 5 minutes)
```bash
crontab -e
```

Add line:
```bash
*/5 * * * * cd /path/to/bookmyseat && python manage.py process_email_queue --limit 50 >> logs/cron.log 2>&1
```

### Verify Cron is Running
```bash
# Check log
tail -f logs/cron.log

# Or check cron logs
grep CRON /var/log/syslog | tail -20
```

### Adjust Frequency as Needed
```bash
# Every minute (for high volume)
* * * * * cd /path/to/bookmyseat && python manage.py process_email_queue --limit 100

# Every hour (for low volume)
0 * * * * cd /path/to/bookmyseat && python manage.py process_email_queue --limit 20
```

---

## Example 6: Django Admin Management

### Access Admin Queue Management
1. Go to: `http://localhost:8000/admin/movies/emailqueueitem/`
2. Filter by Status (Pending, Sent, Failed)
3. View email details
4. Take actions on selected emails

### Bulk Actions

**Retry Failed Emails**:
1. Filter by Status = Failed
2. Check boxes for emails to retry
3. Select "Retry selected emails"
4. Click "Go"

**Mark as Pending**:
1. Filter by Status = Failed
2. Select all
3. Choose "Mark selected as Pending"
4. Click "Go"

**View Delivery Logs**:
1. Go to: `http://localhost:8000/admin/movies/emaillog/`
2. Filter by Status or Log Level
3. Click on an entry to view details
4. See structured details in JSON format

---

## Example 7: Custom Email Template

### Create Custom Template

**File**: `templates/emails/order_status.html`
```html
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; }
        .header { background: #667eea; color: white; padding: 20px; }
        .content { padding: 20px; }
        .button { background: #667eea; color: white; padding: 10px 20px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Order Status Update</h1>
    </div>
    <div class="content">
        <p>Hi {{ user_name }},</p>
        <p>Your order #{{ order_id }} is now {{ status }}.</p>
        <a href="{{ order_url }}" class="button">View Order</a>
    </div>
</body>
</html>
```

**File**: `templates/emails/order_status.txt`
```
Order Status Update
==================

Hi {{ user_name }},

Your order #{{ order_id }} is now {{ status }}.

View order: {{ order_url }}
```

### Queue Custom Email

```python
from movies.models import EmailQueueItem

EmailQueueItem.objects.create(
    user=user,
    to_email=user.email,
    subject=f'Order #{order_id} Status: {status}',
    template_name='emails/order_status.html',
    payload={
        'user_name': user.get_full_name(),
        'order_id': order_id,
        'status': status,
        'order_url': 'https://example.com/orders/123',
    }
)
```

---

## Example 8: Troubleshooting

### Emails Not Sending

**Step 1: Check Configuration**
```python
python manage.py shell
from django.conf import settings

print(f"USE_SMTP_EMAIL: {settings.EMAIL_BACKEND}")
print(f"EMAIL_HOST: {settings.EMAIL_HOST}")
print(f"EMAIL_PORT: {settings.EMAIL_PORT}")
```

**Step 2: Test SMTP Connection**
```python
from django.core.mail import send_mail

try:
    send_mail(
        'Test Subject',
        'Test body',
        'noreply@bookmyseat.com',
        ['test@example.com'],
        fail_silently=False,
    )
    print("✓ Email sent successfully!")
except Exception as e:
    print(f"✗ Error: {e}")
```

**Step 3: Check Email Queue**
```python
from movies.models import EmailQueueItem

# View queued emails
pending = EmailQueueItem.objects.filter(status='pending')
print(f"Pending: {pending.count()}")

# View first email details
email = pending.first()
if email:
    print(f"To: {email.to_email}")
    print(f"Subject: {email.subject}")
    print(f"Attempts: {email.attempts}")
    print(f"Last Error: {email.last_error}")
```

**Step 4: Process Queue Manually**
```bash
python manage.py process_email_queue --limit 1 --force-retry
```

**Step 5: Check Logs**
```bash
tail -50 logs/email_errors.log
```

---

## Example 9: Monitoring Dashboard

### Create Monitoring View

**File**: `movies/views.py`
```python
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from movies.email import get_email_delivery_stats
from movies.models import EmailLog

@staff_member_required
def email_stats(request):
    stats = get_email_delivery_stats()
    recent_logs = EmailLog.objects.order_by('-created_at')[:10]
    
    context = {
        'stats': stats,
        'recent_logs': recent_logs,
    }
    return render(request, 'email_stats.html', context)
```

**File**: `templates/email_stats.html`
```html
{% extends "base.html" %}

{% block content %}
<h1>Email Delivery Statistics</h1>

<div class="stats">
    <div class="stat-box">
        <h3>{{ stats.total }}</h3>
        <p>Total Emails</p>
    </div>
    <div class="stat-box success">
        <h3>{{ stats.sent }}</h3>
        <p>Sent</p>
    </div>
    <div class="stat-box warning">
        <h3>{{ stats.pending }}</h3>
        <p>Pending</p>
    </div>
    <div class="stat-box error">
        <h3>{{ stats.failed }}</h3>
        <p>Failed</p>
    </div>
    <div class="stat-box">
        <h3>{{ stats.success_rate }}%</h3>
        <p>Success Rate</p>
    </div>
</div>

<h2>Recent Events</h2>
<table>
    <thead>
        <tr>
            <th>Time</th>
            <th>Status</th>
            <th>Email</th>
            <th>Message</th>
        </tr>
    </thead>
    <tbody>
        {% for log in recent_logs %}
        <tr>
            <td>{{ log.created_at }}</td>
            <td>{{ log.status }}</td>
            <td>{{ log.email_address }}</td>
            <td>{{ log.message }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endblock %}
```

**File**: `movies/urls.py`
```python
urlpatterns = [
    # ... existing urls ...
    path('admin/email-stats/', email_stats, name='email_stats'),
]
```

---

## Example 10: Database Queries for Analysis

### Email Delivery Report
```python
from movies.models import EmailQueueItem, EmailLog
from django.db.models import Count

# Emails by status
stats = EmailQueueItem.objects.values('status').annotate(
    count=Count('id')
).order_by('status')

for stat in stats:
    print(f"{stat['status']}: {stat['count']}")
```

### Failure Analysis
```python
# Top error messages
failures = EmailLog.objects.filter(
    status='failed'
).values('error_message').annotate(
    count=Count('id')
).order_by('-count')[:5]

print("Top 5 failure reasons:")
for failure in failures:
    print(f"  {failure['error_message'][:80]}: {failure['count']} times")
```

### User Email History
```python
from django.contrib.auth.models import User

user = User.objects.get(username='john_doe')

# All emails sent to this user
emails = EmailQueueItem.objects.filter(user=user).order_by('-created_at')
print(f"Emails sent to {user}: {emails.count()}")

# Last email status
last_email = emails.first()
if last_email:
    print(f"Last email: {last_email.subject} - {last_email.status}")
```

---

## References

- Full Documentation: [EMAIL_SYSTEM.md](../docs/EMAIL_SYSTEM.md)
- Integration Guide: [EMAIL_INTEGRATION_GUIDE.md](../docs/EMAIL_INTEGRATION_GUIDE.md)
- Deployment Guide: [DEPLOYMENT_GUIDE.md](../docs/DEPLOYMENT_GUIDE.md)
