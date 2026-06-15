import time
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from datetime import timedelta
from movies.models import PaymentOrder, Booking, Seat

logger = logging.getLogger('movies')


class Command(BaseCommand):
    """
    Background scheduler command to release expired seat reservations.
    
    Can run as a one-off task or continuously in a loop (daemon mode).
    
    Usage:
        python manage.py release_expired_bookings --loop --interval 5
    """
    help = 'Automatically release expired seat reservations (pending orders older than 2 minutes).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--loop',
            action='store_true',
            help='Run continuously in a loop (daemon mode)',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=5,
            help='Interval in seconds between runs in loop mode (default: 5)',
        )

    def handle(self, *args, **options):
        loop = options['loop']
        interval = options['interval']

        if loop:
            self.stdout.write(self.style.SUCCESS(
                f"Starting background scheduler: releasing expired reservations every {interval} seconds...\n"
            ))
            try:
                while True:
                    count = self.release_expired()
                    if count > 0:
                        self.stdout.write(self.style.SUCCESS(f"[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] Released {count} expired order(s)."))
                    time.sleep(interval)
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("Stopping background scheduler."))
        else:
            self.stdout.write("Running one-off release of expired bookings...")
            count = self.release_expired()
            if count > 0:
                self.stdout.write(self.style.SUCCESS(f"Successfully released {count} expired order(s)."))
            else:
                self.stdout.write("No expired orders found.")

    def release_expired(self):
        threshold = timezone.now() - timedelta(minutes=2)
        
        # Select orders that are pending and created before the 2-minute threshold
        expired_orders = PaymentOrder.objects.filter(
            status=PaymentOrder.Status.PENDING,
            created_at__lt=threshold
        )
        
        count = 0
        for order in expired_orders:
            try:
                with transaction.atomic():
                    # Lock the specific payment order using select_for_update
                    order_locked = PaymentOrder.objects.select_for_update().get(id=order.id)
                    if order_locked.status == PaymentOrder.Status.PENDING:
                        order_locked.status = PaymentOrder.Status.EXPIRED
                        order_locked.idempotency_key = f"{order_locked.idempotency_key}_expired_{order_locked.id}"
                        order_locked.save(update_fields=['status', 'idempotency_key'])
                        
                        # Release all bookings associated with this payment order
                        bookings = order_locked.bookings.all()
                        seat_ids = [b.seat_id for b in bookings]
                        bookings.update(status=Booking.Status.FAILED)
                        
                        # Set associated seats to available
                        released = Seat.objects.filter(id__in=seat_ids).update(is_booked=False)
                        
                        count += 1
                        logger.info(
                            f"Automatically released expired PaymentOrder {order_locked.id} "
                            f"(payment_id={order_locked.payment_id}) and released {released} seat(s)."
                        )
            except Exception as e:
                logger.error(f"Error releasing expired order {order.id}: {str(e)}", exc_info=True)
                continue
                
        return count
