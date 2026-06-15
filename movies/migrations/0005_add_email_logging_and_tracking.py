# Generated migration for EmailLog model and EmailQueueItem enhancements

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0004_add_payment_and_email_queue'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Add new fields to EmailQueueItem
        migrations.AddField(
            model_name='emailqueueitem',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name='emailqueueitem',
            name='payload',
            field=models.JSONField(default=dict, help_text='Email template context data'),
        ),
        migrations.AlterField(
            model_name='emailqueueitem',
            name='template_name',
            field=models.CharField(default='emails/booking_confirmation.html', help_text='Template path', max_length=255),
        ),
        migrations.AlterField(
            model_name='emailqueueitem',
            name='attempts',
            field=models.PositiveSmallIntegerField(default=0, help_text='Number of send attempts'),
        ),
        migrations.AlterField(
            model_name='emailqueueitem',
            name='max_attempts',
            field=models.PositiveSmallIntegerField(default=5, help_text='Maximum retry attempts'),
        ),
        migrations.AlterField(
            model_name='emailqueueitem',
            name='last_error',
            field=models.TextField(blank=True, help_text='Last error message', null=True),
        ),
        migrations.AlterField(
            model_name='emailqueueitem',
            name='next_attempt_at',
            field=models.DateTimeField(db_index=True, default=timezone.now, help_text='Next retry time'),
        ),
        migrations.AlterField(
            model_name='emailqueueitem',
            name='sent_at',
            field=models.DateTimeField(blank=True, help_text='When email was successfully sent', null=True),
        ),
        migrations.AlterField(
            model_name='emailqueueitem',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')], db_index=True, default='pending', max_length=10),
        ),
        migrations.AlterField(
            model_name='emailqueueitem',
            name='to_email',
            field=models.EmailField(db_index=True, max_length=254),
        ),
        migrations.AlterField(
            model_name='emailqueueitem',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AddIndex(
            model_name='emailqueueitem',
            index=models.Index(fields=['status', 'next_attempt_at'], name='movies_email_status_next_idx'),
        ),
        migrations.AddIndex(
            model_name='emailqueueitem',
            index=models.Index(fields=['user', 'created_at'], name='movies_email_user_date_idx'),
        ),
        
        # Create EmailLog model
        migrations.CreateModel(
            name='EmailLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email_address', models.EmailField(db_index=True, max_length=254)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('sending', 'Sending'), ('sent', 'Sent'), ('delivered', 'Delivered'), ('failed', 'Failed'), ('bounced', 'Bounced'), ('complained', 'Complained')], db_index=True, max_length=15)),
                ('message', models.TextField(blank=True, help_text='Human-readable log message')),
                ('error_message', models.TextField(blank=True, help_text='Error details if applicable')),
                ('log_level', models.CharField(choices=[('DEBUG', 'Debug'), ('INFO', 'Info'), ('WARNING', 'Warning'), ('ERROR', 'Error'), ('CRITICAL', 'Critical')], default='INFO', max_length=10)),
                ('details', models.JSONField(default=dict, help_text='Additional structured data')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('email_queue_item', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='logs', to='movies.emailqueueitem', db_index=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_logs', to=settings.AUTH_USER_MODEL, db_index=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='emaillog',
            index=models.Index(fields=['user', '-created_at'], name='movies_email_user_date_log_idx'),
        ),
        migrations.AddIndex(
            model_name='emaillog',
            index=models.Index(fields=['status', '-created_at'], name='movies_email_status_date_idx'),
        ),
        migrations.AddIndex(
            model_name='emaillog',
            index=models.Index(fields=['email_queue_item', '-created_at'], name='movies_email_queue_date_idx'),
        ),
    ]
