from django.db import migrations

def fix_legacy_idempotency_keys(apps, schema_editor):
    PaymentOrder = apps.get_model('movies', 'PaymentOrder')
    # Fetch all orders that are not pending or completed
    qs = PaymentOrder.objects.filter(status__in=['failed', 'expired', 'cancelled'])
    for o in qs:
        # Check if the key does not already end with the status suffix
        suffix = f"_{o.status}_{o.id}"
        if o.idempotency_key and not o.idempotency_key.endswith(suffix):
            o.idempotency_key = f"{o.idempotency_key}{suffix}"
            o.save(update_fields=['idempotency_key'])

class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0009_alter_booking_seat'),
    ]

    operations = [
        migrations.RunPython(fix_legacy_idempotency_keys, reverse_code=migrations.RunPython.noop),
    ]
