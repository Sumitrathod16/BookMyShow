from datetime import timedelta
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings

from movies.email import send_email_task, mask_email, log_email_event
from movies.models import EmailQueueItem, EmailLog

logger = logging.getLogger('movies.email')


class Command(BaseCommand):
    """
    Process pending email queue items with exponential backoff retry logic.
    
    This command:
    - Sends pending emails that are ready for delivery
    - Implements exponential backoff for failed deliveries
    - Logs all events for monitoring and debugging
    - Marks emails as permanently failed after max attempts
    
    Run periodically via cron or celery beat:
        python manage.py process_email_queue --limit 50
    """
    help = 'Process pending email queue items and retry failures with exponential backoff.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=20,
            help='Maximum number of email tasks to process in this run (default: 20)',
        )
        parser.add_argument(
            '--force-retry',
            action='store_true',
            help='Force retry of failed emails regardless of next_attempt_at time',
        )
        parser.add_argument(
            '--status',
            choices=['pending', 'all'],
            default='pending',
            help='Filter emails by status (default: pending only)',
        )

    def handle(self, *args, **options):
        limit = options['limit']
        force_retry = options['force_retry']
        status_filter = options['status']
        now = timezone.now()

        # Build query for emails to process
        query = EmailQueueItem.objects.select_related('user')
        
        if status_filter == 'pending':
            query = query.filter(status=EmailQueueItem.Status.PENDING)
        
        # Check next_attempt_at unless force_retry is set
        if not force_retry:
            query = query.filter(next_attempt_at__lte=now)
        
        # Order by priority: pending first, then by creation time
        tasks = query.order_by('created_at')[:limit]

        if not tasks:
            self.stdout.write(self.style.WARNING('No email tasks to process.'))
            logger.info('No pending email tasks to process. limit=%d, force_retry=%s', limit, force_retry)
            return

        total_tasks = len(tasks)
        successful = 0
        failed = 0
        
        self.stdout.write(f'Processing {total_tasks} email task(s)...\n')

        for task in tasks:
            try:
                self.stdout.write(f'[{successful + failed + 1}/{total_tasks}] Sending email to {mask_email(task.to_email)}... ', ending='')
                
                # Update status to sending
                task.status = EmailQueueItem.Status.SENDING
                task.save(update_fields=['status'])
                
                log_email_event(
                    task=task,
                    user=task.user,
                    status=EmailLog.Status.SENDING,
                    message=f'Starting email delivery attempt {task.attempts + 1}/{task.max_attempts}',
                    log_level=EmailLog.LogLevel.INFO,
                )
                
                # Attempt to send email
                send_email_task(task)
                
                # Mark as sent
                task.status = EmailQueueItem.Status.SENT
                task.sent_at = timezone.now()
                task.attempts += 1
                task.last_error = ''
                task.save(update_fields=['status', 'sent_at', 'attempts', 'last_error'])
                
                log_email_event(
                    task=task,
                    user=task.user,
                    status=EmailLog.Status.SENT,
                    message=f'Email delivered successfully after {task.attempts} attempt(s)',
                    log_level=EmailLog.LogLevel.INFO,
                )
                
                self.stdout.write(self.style.SUCCESS('✓ SENT'))
                successful += 1
                logger.info('Email task %s sent successfully to %s', task.pk, mask_email(task.to_email))
                
            except Exception as exc:
                task.attempts += 1
                task.last_error = str(exc)
                
                # Check if we've exceeded max attempts
                if task.attempts >= task.max_attempts:
                    task.status = EmailQueueItem.Status.FAILED
                    task.next_attempt_at = None
                    task.save(update_fields=['status', 'attempts', 'last_error', 'next_attempt_at'])
                    
                    log_email_event(
                        task=task,
                        user=task.user,
                        status=EmailLog.Status.FAILED,
                        error_message=str(exc),
                        message=f'Email delivery failed permanently after {task.attempts} attempts',
                        log_level=EmailLog.LogLevel.ERROR,
                        details={'final_error': str(exc)},
                    )
                    
                    self.stdout.write(self.style.ERROR(f'✗ FAILED (Max retries exceeded)'))
                    failed += 1
                    logger.error(
                        'Email task %s failed permanently after %d attempts: %s',
                        task.pk,
                        task.attempts,
                        exc,
                        exc_info=True,
                    )
                else:
                    # Schedule retry with exponential backoff
                    retry_delay_seconds = min(2 ** task.attempts * 60, 3600)  # Cap at 1 hour
                    task.next_attempt_at = timezone.now() + timedelta(seconds=retry_delay_seconds)
                    task.save(update_fields=['status', 'attempts', 'last_error', 'next_attempt_at'])
                    
                    log_email_event(
                        task=task,
                        user=task.user,
                        status=EmailLog.Status.FAILED,
                        error_message=str(exc),
                        message=f'Email delivery failed. Retry scheduled in {retry_delay_seconds} seconds',
                        log_level=EmailLog.LogLevel.WARNING,
                        details={
                            'attempt': task.attempts,
                            'max_attempts': task.max_attempts,
                            'retry_delay_seconds': retry_delay_seconds,
                            'error': str(exc),
                        },
                    )
                    
                    self.stdout.write(self.style.WARNING(
                        f'✗ FAILED (Retry {task.attempts}/{task.max_attempts} in {retry_delay_seconds}s)'
                    ))
                    failed += 1
                    logger.warning(
                        'Email task %s failed (attempt %d/%d), retry scheduled in %d seconds: %s',
                        task.pk,
                        task.attempts,
                        task.max_attempts,
                        retry_delay_seconds,
                        exc,
                        exc_info=True,
                    )

        # Print summary
        self.stdout.write('\n' + '=' * 60)
        self.stdout.write(self.style.SUCCESS(f'✓ Successful: {successful}'))
        if failed > 0:
            self.stdout.write(self.style.WARNING(f'✗ Failed: {failed}'))
        self.stdout.write('=' * 60)
        
        logger.info(
            'Email queue processing completed: total=%d, successful=%d, failed=%d',
            total_tasks,
            successful,
            failed,
        )
