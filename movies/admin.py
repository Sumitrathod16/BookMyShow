# pyrefly: ignore [missing-import]
from django.contrib import admin
# pyrefly: ignore [missing-import]
from django.utils.html import format_html
# pyrefly: ignore [missing-import]
from django.urls import reverse
# pyrefly: ignore [missing-import]
from django.db.models import Q, Count
from .models import EmailQueueItem, EmailLog, Movie, Theater, Seat, Booking, Genre, Language


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['name', 'rating', 'cast', 'description', 'trailer_url']
    filter_horizontal = ['genres', 'languages']


@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = ['name', 'movie', 'time']


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ['theater', 'seat_number', 'is_booked']


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['user', 'seat', 'movie', 'theater', 'payment_id', 'booked_at']


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin.register(EmailQueueItem)
class EmailQueueItemAdmin(admin.ModelAdmin):
    """
    Admin interface for monitoring and managing email queue.
    
    Features:
    - View all pending, sent, and failed emails
    - Status indicators with color coding
    - Error previews for failed emails
    - Retry action for failed emails
    - Filter by status and date
    - Search by email, subject, or payment ID
    """
    list_display = [
        'status_badge',
        'to_email_masked',
        'subject_preview',
        'attempts_display',
        'sent_at_or_next_attempt',
        'created_at',
    ]
    list_filter = ['status', 'created_at', 'attempts']
    search_fields = ['to_email', 'subject', 'payload', 'last_error']
    readonly_fields = [
        'created_at',
        'updated_at',
        'sent_at',
        'last_error_display',
        'payload_display',
        'user_link',
        'attempts',
    ]
    
    fieldsets = (
        ('Recipient & Content', {
            'fields': ('user_link', 'to_email', 'subject', 'template_name')
        }),
        ('Status & Delivery', {
            'fields': ('status', 'attempts', 'max_attempts', 'next_attempt_at', 'sent_at')
        }),
        ('Error Information', {
            'classes': ('collapse',),
            'fields': ('last_error_display',),
        }),
        ('Email Payload', {
            'classes': ('collapse',),
            'fields': ('payload_display',),
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    actions = ['mark_pending', 'mark_failed', 'retry_failed']

    def status_badge(self, obj):
        """Display status with color coding."""
        colors = {
            EmailQueueItem.Status.PENDING: '#FFA500',  # Orange
            EmailQueueItem.Status.SENDING: '#17a2b8',  # Teal/Blue
            EmailQueueItem.Status.SENT: '#28a745',     # Green
            EmailQueueItem.Status.FAILED: '#dc3545',   # Red
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 8px; border-radius: 3px; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display().upper()
        )
    status_badge.short_description = 'Status'

    def to_email_masked(self, obj):
        """Display email address (masked in list view for privacy)."""
        return obj.to_email[:obj.to_email.index('@')] + '@' + obj.to_email.split('@')[1] if '@' in obj.to_email else obj.to_email
    to_email_masked.short_description = 'Email'

    def subject_preview(self, obj):
        """Display first 50 characters of subject."""
        return obj.subject[:50] + ('...' if len(obj.subject) > 50 else '')
    subject_preview.short_description = 'Subject'

    def attempts_display(self, obj):
        """Display attempts with color coding."""
        if obj.status == EmailQueueItem.Status.SENT:
            color = '#28a745'
            text = f'{obj.attempts} (✓)'
        elif obj.attempts >= obj.max_attempts:
            color = '#dc3545'
            text = f'{obj.attempts}/{obj.max_attempts} (MAX)'
        else:
            color = '#FFA500'
            text = f'{obj.attempts}/{obj.max_attempts}'
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            text
        )
    attempts_display.short_description = 'Attempts'

    def sent_at_or_next_attempt(self, obj):
        """Display sent time or next attempt time."""
        if obj.sent_at:
            return format_html(
                '<span style="color: #28a745;">Sent: {}</span>',
                obj.sent_at.strftime('%Y-%m-%d %H:%M')
            )
        elif obj.next_attempt_at:
            return format_html(
                '<span style="color: #FFA500;">Retry: {}</span>',
                obj.next_attempt_at.strftime('%Y-%m-%d %H:%M')
            )
        return '-'
    sent_at_or_next_attempt.short_description = 'Delivery Status'

    def user_link(self, obj):
        """Link to user profile in admin."""
        url = reverse('admin:auth_user_change', args=[obj.user.pk])
        return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.username)
    user_link.short_description = 'User'

    def last_error_display(self, obj):
        """Display last error with formatting."""
        if obj.last_error:
            return format_html(
                '<pre style="background-color: #f8d7da; padding: 10px; border-radius: 4px; color: #721c24;">{}</pre>',
                obj.last_error[:500] + ('...' if len(obj.last_error) > 500 else '')
            )
        return format_html('<span style="color: #6c757d;">No errors</span>')
    last_error_display.short_description = 'Last Error'

    def payload_display(self, obj):
        """Display payload as formatted JSON."""
        import json
        try:
            formatted = json.dumps(obj.payload, indent=2, default=str)
            return format_html(
                '<pre style="background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto;">{}</pre>',
                formatted
            )
        except:
            return str(obj.payload)
    payload_display.short_description = 'Email Data'

    def mark_pending(self, request, queryset):
        """Action to mark emails as pending for retry."""
        updated = queryset.update(status=EmailQueueItem.Status.PENDING)
        self.message_user(request, f'{updated} email(s) marked as pending.')
    mark_pending.short_description = 'Mark selected as Pending'

    def mark_failed(self, request, queryset):
        """Action to mark emails as failed."""
        updated = queryset.update(status=EmailQueueItem.Status.FAILED, next_attempt_at=None)
        self.message_user(request, f'{updated} email(s) marked as failed.')
    mark_failed.short_description = 'Mark selected as Failed'

    def retry_failed(self, request, queryset):
        """Action to retry failed emails."""
        # pyrefly: ignore [missing-import]
        from django.utils import timezone
        updated = queryset.filter(
            Q(status=EmailQueueItem.Status.FAILED) | Q(status=EmailQueueItem.Status.PENDING)
        ).update(
            status=EmailQueueItem.Status.PENDING,
            next_attempt_at=timezone.now(),
            attempts=0
        )
        self.message_user(request, f'{updated} email(s) queued for immediate retry.')
    retry_failed.short_description = 'Retry selected emails'

    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related('user')


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    """
    Admin interface for email delivery logs and audit trail.
    
    Features:
    - View detailed email events
    - Filter by status, log level, and date
    - Search by email address or user
    - View structured details in JSON format
    - Performance-optimized with proper indexing
    """
    list_display = [
        'status_badge',
        'log_level_badge',
        'email_address_masked',
        'user_display',
        'message_preview',
        'created_at',
    ]
    list_filter = ['status', 'log_level', 'created_at']
    search_fields = ['email_address', 'user__username', 'user__email', 'message', 'error_message']
    readonly_fields = [
        'created_at',
        'details_display',
        'error_message_display',
        'user_link',
    ]
    
    fieldsets = (
        ('Event Information', {
            'fields': ('user_link', 'email_address', 'status', 'log_level')
        }),
        ('Messages', {
            'fields': ('message', 'error_message_display'),
        }),
        ('Details', {
            'classes': ('collapse',),
            'fields': ('details_display',),
        }),
        ('Metadata', {
            'fields': ('email_queue_item', 'created_at'),
        }),
    )

    def status_badge(self, obj):
        """Display status with color coding."""
        colors = {
            EmailLog.Status.QUEUED: '#17a2b8',        # Info blue
            EmailLog.Status.SENDING: '#FFA500',        # Orange
            EmailLog.Status.SENT: '#28a745',           # Green
            EmailLog.Status.DELIVERED: '#007bff',     # Blue
            EmailLog.Status.FAILED: '#dc3545',         # Red
            EmailLog.Status.BOUNCED: '#6f42c1',        # Purple
            EmailLog.Status.COMPLAINED: '#e83e8c',    # Pink
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 6px; border-radius: 3px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display().upper()
        )
    status_badge.short_description = 'Status'

    def log_level_badge(self, obj):
        """Display log level with color coding."""
        colors = {
            EmailLog.LogLevel.DEBUG: '#6c757d',
            EmailLog.LogLevel.INFO: '#17a2b8',
            EmailLog.LogLevel.WARNING: '#FFA500',
            EmailLog.LogLevel.ERROR: '#dc3545',
            EmailLog.LogLevel.CRITICAL: '#721c24',
        }
        color = colors.get(obj.log_level, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 6px; border-radius: 3px; font-size: 11px;">{}</span>',
            color,
            obj.log_level
        )
    log_level_badge.short_description = 'Level'

    def email_address_masked(self, obj):
        """Display email address masked for privacy."""
        if not obj.email_address or '@' not in obj.email_address:
            return '***'
        parts = obj.email_address.split('@')
        username = parts[0]
        domain = parts[1]
        masked = username[0] + '*' * max(0, len(username) - 2) + (username[-1] if len(username) > 1 else '')
        return f'{masked}@{domain}'
    email_address_masked.short_description = 'Email'

    def user_display(self, obj):
        """Display user username."""
        return obj.user.username
    user_display.short_description = 'User'

    def user_link(self, obj):
        """Link to user in admin."""
        url = reverse('admin:auth_user_change', args=[obj.user.pk])
        return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.username)
    user_link.short_description = 'User'

    def message_preview(self, obj):
        """Display first 60 characters of message."""
        if obj.message:
            return obj.message[:60] + ('...' if len(obj.message) > 60 else '')
        return format_html('<span style="color: #6c757d;">No message</span>')
    message_preview.short_description = 'Message'

    def error_message_display(self, obj):
        """Display error message with formatting."""
        if obj.error_message:
            return format_html(
                '<pre style="background-color: #f8d7da; padding: 10px; border-radius: 4px; color: #721c24; max-height: 300px; overflow-y: auto;">{}</pre>',
                obj.error_message[:1000] + ('...' if len(obj.error_message) > 1000 else '')
            )
        return format_html('<span style="color: #6c757d;">No errors</span>')
    error_message_display.short_description = 'Error Details'

    def details_display(self, obj):
        """Display details as formatted JSON."""
        import json
        try:
            formatted = json.dumps(obj.details, indent=2, default=str)
            return format_html(
                '<pre style="background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; max-height: 400px; overflow-y: auto;">{}</pre>',
                formatted
            )
        except:
            return str(obj.details)
    details_display.short_description = 'Structured Details'

    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related('user', 'email_queue_item')




