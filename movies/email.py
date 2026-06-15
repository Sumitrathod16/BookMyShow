import logging
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.template import TemplateDoesNotExist
from django.utils.html import strip_tags
from django.utils import timezone
from .models import EmailQueueItem, EmailLog

logger = logging.getLogger('movies.email')
sensitive_logger = logging.getLogger('movies.email.sensitive')


def mask_email(email: str) -> str:
    """Mask email address for logging purposes."""
    if not email or '@' not in email:
        return '***'
    parts = email.split('@')
    username = parts[0]
    domain = parts[1]
    masked_username = username[0] + '*' * (len(username) - 2) + username[-1] if len(username) > 2 else '*' * len(username)
    return f'{masked_username}@{domain}'


def mask_payment_id(payment_id: Optional[str]) -> str:
    """Mask payment ID for logging purposes."""
    if not payment_id:
        return '***'
    return payment_id[:4] + '*' * (len(payment_id) - 8) + payment_id[-4:]


def sanitize_payload_for_logging(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Remove/mask sensitive data from payload for logging."""
    sanitized = payload.copy()
    if 'payment_id' in sanitized:
        sanitized['payment_id'] = mask_payment_id(sanitized['payment_id'])
    return sanitized


def enqueue_booking_confirmation_email(bookings: List) -> Optional[EmailQueueItem]:
    """
    Queue a booking confirmation email for the user.
    
    Does not block - runs asynchronously via process_email_queue management command.
    
    Args:
        bookings: List of Booking objects for the same user/show
        
    Returns:
        EmailQueueItem if successfully queued, None otherwise
    """
    if not bookings:
        logger.warning('enqueue_booking_confirmation_email called with empty bookings list')
        return None

    booking = bookings[0]
    user = booking.user
    
    if not user.email:
        logger.warning('Booking confirmation skipped; user %s has no email address.', user.pk)
        EmailLog.objects.create(
            email_queue_item=None,
            user=user,
            email_address=user.email or '',
            status=EmailLog.Status.FAILED,
            error_message='User has no email address',
            log_level=EmailLog.LogLevel.WARNING,
        )
        return None

    # Prepare email context with all booking details
    payload = {
        'user_name': user.get_full_name() or user.username,
        'user_email': mask_email(user.email),  # Masked email for template
        'movie_name': booking.movie.name,
        'theater_name': booking.theater.name,
        'show_time': booking.theater.time.isoformat(),
        'show_date': booking.theater.time.strftime('%B %d, %Y'),
        'show_time_formatted': booking.theater.time.strftime('%I:%M %p'),
        'seat_numbers': sorted([b.seat.seat_number for b in bookings]),
        'payment_id': mask_payment_id(booking.payment_id) if booking.payment_id else 'N/A',
        'booking_time': booking.booked_at.isoformat(),
        'booking_time_formatted': booking.booked_at.strftime('%B %d, %Y at %I:%M %p'),
        'total_seats': len(bookings),
        'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@bookmyseat.com'),
    }

    try:
        # Create email queue item
        email_queue_item = EmailQueueItem.objects.create(
            user=user,
            to_email=user.email,
            subject=f'Your Booking Confirmation: {payload["movie_name"]}',
            template_name='emails/booking_confirmation.html',
            payload=payload,
            max_attempts=getattr(settings, 'EMAIL_MAX_ATTEMPTS', 5),
        )
        
        logger.info(
            'Queued booking confirmation email: user_id=%s, email=%s, seats=%d, payment_id=%s',
            user.pk,
            mask_email(user.email),
            len(bookings),
            mask_payment_id(booking.payment_id),
        )
        
        # Log the queue action
        EmailLog.objects.create(
            email_queue_item=email_queue_item,
            user=user,
            email_address=user.email,
            status=EmailLog.Status.QUEUED,
            log_level=EmailLog.LogLevel.INFO,
            details={'booking_ids': [b.id for b in bookings], 'seats': payload['seat_numbers']},
        )
        
        return email_queue_item
        
    except Exception as exc:
        logger.exception(
            'Error queuing booking confirmation email for user %s: %s',
            user.pk,
            exc,
        )
        EmailLog.objects.create(
            user=user,
            email_address=user.email or '',
            status=EmailLog.Status.FAILED,
            error_message=f'Failed to queue email: {str(exc)}',
            log_level=EmailLog.LogLevel.ERROR,
        )
        raise


def send_email_task(task: EmailQueueItem) -> bool:
    """
    Send an email from the queue.
    
    Handles template rendering with context, both HTML and plain text versions,
    and sends via configured SMTP backend.
    
    Args:
        task: EmailQueueItem to send
        
    Returns:
        True if successful, False otherwise (exception raised on error)
        
    Raises:
        ValueError: If recipient email is missing
        RuntimeError: If email send fails
    """
    if not task.to_email:
        error_msg = 'Email task has no recipient.'
        task.last_error = error_msg
        logger.error('Email task %s: %s', task.pk, error_msg)
        raise ValueError(error_msg)

    try:
        # Render email templates with context
        context = task.payload.copy()
        html_body = render_to_string(task.template_name, context)
        
        try:
            text_body = render_to_string(task.template_name.replace('.html', '.txt'), context)
        except TemplateDoesNotExist:
            # Fallback to stripping HTML tags if text template doesn't exist
            text_body = strip_tags(html_body)

        # Create email message with both HTML and plain text alternatives
        message = EmailMultiAlternatives(
            subject=task.subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[task.to_email],
        )
        message.attach_alternative(html_body, 'text/html')

        # Send email with connection management
        with get_connection() as connection:
            num_sent = connection.send_messages([message])

        if num_sent != 1:
            error_msg = f'Expected to send 1 email, but sent {num_sent}.'
            logger.error('Email task %s: %s', task.pk, error_msg)
            raise RuntimeError(error_msg)

        logger.info(
            'Email sent successfully: task_id=%s, email=%s, subject=%s',
            task.pk,
            mask_email(task.to_email),
            task.subject,
        )
        
        return True
        
    except Exception as exc:
        logger.error(
            'Failed to send email task %s to %s: %s',
            task.pk,
            mask_email(task.to_email),
            str(exc),
            exc_info=True,
        )
        raise


def log_email_event(
    task: Optional[EmailQueueItem],
    user,
    status: str,
    message: str = '',
    error_message: str = '',
    log_level: str = EmailLog.LogLevel.INFO,
    details: Optional[Dict] = None,
) -> EmailLog:
    """
    Log an email event for monitoring and debugging.
    
    Args:
        task: EmailQueueItem associated with the event
        user: User object
        status: Status of the email (QUEUED, SENT, FAILED, etc.)
        message: Informational message
        error_message: Error message if applicable
        log_level: Log level (INFO, WARNING, ERROR)
        details: Additional details to store
        
    Returns:
        EmailLog instance
    """
    email_log = EmailLog.objects.create(
        email_queue_item=task,
        user=user,
        email_address=task.to_email if task else '',
        status=status,
        message=message,
        error_message=error_message,
        log_level=log_level,
        details=details or {},
    )
    return email_log


def get_email_delivery_stats() -> Dict[str, Any]:
    """
    Get email delivery statistics for monitoring.
    
    Returns:
        Dictionary with delivery stats including success rate, failure count, etc.
    """
    total = EmailQueueItem.objects.count()
    sent = EmailQueueItem.objects.filter(status=EmailQueueItem.Status.SENT).count()
    failed = EmailQueueItem.objects.filter(status=EmailQueueItem.Status.FAILED).count()
    pending = EmailQueueItem.objects.filter(status=EmailQueueItem.Status.PENDING).count()
    
    success_rate = (sent / total * 100) if total > 0 else 0
    
    return {
        'total': total,
        'sent': sent,
        'failed': failed,
        'pending': pending,
        'success_rate': round(success_rate, 2),
    }
