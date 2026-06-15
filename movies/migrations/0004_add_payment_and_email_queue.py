from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0003_filter_performance_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='payment_id',
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
        migrations.CreateModel(
            name='EmailQueueItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('to_email', models.EmailField(max_length=254)),
                ('subject', models.CharField(max_length=255)),
                ('template_name', models.CharField(default='emails/booking_confirmation.html', max_length=255)),
                ('payload', models.JSONField(default=dict)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')], default='pending', max_length=10)),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('max_attempts', models.PositiveSmallIntegerField(default=5)),
                ('last_error', models.TextField(blank=True, null=True)),
                ('next_attempt_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_queue', to='auth.user')),
            ],
            options={
                'ordering': ['status', 'next_attempt_at', 'created_at'],
            },
        ),
    ]
