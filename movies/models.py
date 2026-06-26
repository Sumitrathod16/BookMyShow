# pyrefly: ignore [missing-import]
from django.db import models
# pyrefly: ignore [missing-import]
from django.contrib.auth.models import User
# pyrefly: ignore [missing-import]
from django.utils import timezone
from django.core.exceptions import ValidationError
import re
from urllib.parse import urlparse, parse_qs


def extract_youtube_id(url):
    if not url:
        return None
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ''
        if hostname.startswith('www.'):
            hostname = hostname[4:]
        
        if hostname not in ('youtube.com', 'youtu.be'):
            return None
        
        video_id = None
        if hostname == 'youtu.be':
            path = parsed.path.strip('/')
            if len(path) == 11:
                video_id = path
        elif hostname == 'youtube.com':
            if parsed.path == '/watch':
                qs = parse_qs(parsed.query)
                v_list = qs.get('v')
                if v_list:
                    video_id = v_list[0]
            elif parsed.path.startswith('/embed/'):
                parts = parsed.path.strip('/').split('/')
                if len(parts) == 2 and parts[0] == 'embed':
                    video_id = parts[1]
        
        if video_id and re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
            return video_id
    except Exception:
        pass
    return None


def validate_youtube_url(value):
    if not value:
        return
    if not extract_youtube_id(value):
        raise ValidationError("Invalid YouTube URL. Please provide a valid YouTube link (e.g. youtube.com or youtu.be).")


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True, db_index=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Language(models.Model):
    name = models.CharField(max_length=100, unique=True, db_index=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Movie(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    image = models.ImageField(upload_to="movies/")
    rating = models.DecimalField(max_digits=3, decimal_places=1, db_index=True)
    cast = models.TextField()
    description = models.TextField(blank=True, null=True)
    genres = models.ManyToManyField(Genre, related_name='movies', blank=True)
    languages = models.ManyToManyField(Language, related_name='movies', blank=True)
    trailer_url = models.URLField(blank=True, null=True, validators=[validate_youtube_url], help_text="YouTube URL of the trailer")

    @property
    def youtube_video_id(self):
        return extract_youtube_id(self.trailer_url)

    @property
    def youtube_embed_url(self):
        video_id = self.youtube_video_id
        if video_id:
            return f"https://www.youtube.com/embed/{video_id}"
        return None

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Theater(models.Model):
    name = models.CharField(max_length=255)
    movie = models.ForeignKey(Movie,on_delete=models.CASCADE,related_name='theaters')
    time= models.DateTimeField()
    ticket_price = models.DecimalField(max_digits=6, decimal_places=2, default=12.00)

    def __str__(self):
        return f'{self.name} - {self.movie.name} at {self.time}'

class Seat(models.Model):
    theater = models.ForeignKey(Theater,on_delete=models.CASCADE,related_name='seats')
    seat_number = models.CharField(max_length=10)
    is_booked=models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['theater', 'is_booked']),
        ]

    def __str__(self):
        return f'{self.seat_number} in {self.theater.name}'


class PaymentOrder(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'
        EXPIRED = 'expired', 'Expired'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_orders')
    payment_id = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)
    idempotency_key = models.CharField(max_length=255, unique=True, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"Order {self.id} - {self.status} (${self.amount})"


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CONFIRMED = 'confirmed', 'Confirmed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    seat = models.ForeignKey(Seat, on_delete=models.CASCADE)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)
    theater = models.ForeignKey(Theater, on_delete=models.CASCADE)
    payment_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CONFIRMED, db_index=True)
    payment_order = models.ForeignKey(PaymentOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings')
    booked_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'booked_at']),
            models.Index(fields=['status', 'movie']),
        ]

    def __str__(self):
        return f'Booking by {self.user.username} for {self.seat.seat_number} at {self.theater.name}'


class EmailQueueItem(models.Model):
    """
    Queue item for asynchronous email sending with retry logic.
    
    Emails are created synchronously after booking but sent asynchronously
    via the process_email_queue management command to avoid blocking the API.
    """
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENDING = 'sending', 'Sending'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_queue')
    to_email = models.EmailField(db_index=True)
    subject = models.CharField(max_length=255)
    template_name = models.CharField(max_length=255, default='emails/booking_confirmation.html')
    payload = models.JSONField(default=dict, help_text='Email template context data')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0, help_text='Number of send attempts')
    max_attempts = models.PositiveSmallIntegerField(default=5, help_text='Maximum retry attempts')
    last_error = models.TextField(blank=True, null=True, help_text='Last error message')
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True, help_text='Next retry time')
    sent_at = models.DateTimeField(blank=True, null=True, help_text='When email was successfully sent')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['status', 'next_attempt_at', 'created_at']
        indexes = [
            models.Index(fields=['status', 'next_attempt_at']),
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f'Email task {self.pk} to {self.to_email} ({self.status})'
    
    def is_retriable(self) -> bool:
        """Check if this email can still be retried."""
        return self.status == self.Status.PENDING and self.attempts < self.max_attempts


class EmailLog(models.Model):
    """
    Detailed log of email events for monitoring, debugging, and audit trail.
    
    Tracks all email lifecycle events: queuing, sending, delivery, failures, retries.
    """
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        SENDING = 'sending', 'Sending'
        SENT = 'sent', 'Sent'
        DELIVERED = 'delivered', 'Delivered'
        FAILED = 'failed', 'Failed'
        BOUNCED = 'bounced', 'Bounced'
        COMPLAINED = 'complained', 'Complained'

    class LogLevel(models.TextChoices):
        DEBUG = 'DEBUG', 'Debug'
        INFO = 'INFO', 'Info'
        WARNING = 'WARNING', 'Warning'
        ERROR = 'ERROR', 'Error'
        CRITICAL = 'CRITICAL', 'Critical'

    email_queue_item = models.ForeignKey(
        EmailQueueItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='logs',
        db_index=True,
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_logs', db_index=True)
    email_address = models.EmailField(db_index=True)
    status = models.CharField(max_length=15, choices=Status.choices, db_index=True)
    message = models.TextField(blank=True, help_text='Human-readable log message')
    error_message = models.TextField(blank=True, help_text='Error details if applicable')
    log_level = models.CharField(max_length=10, choices=LogLevel.choices, default=LogLevel.INFO)
    details = models.JSONField(default=dict, help_text='Additional structured data')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['email_queue_item', '-created_at']),
        ]

    def __str__(self):
        return f'EmailLog {self.pk}: {self.status} ({self.log_level})'