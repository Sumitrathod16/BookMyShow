import json
import hmac
import hashlib
from datetime import timedelta
# pyrefly: ignore [missing-import]
from django.test import TestCase, TransactionTestCase, Client
# pyrefly: ignore [missing-import]
from django.utils import timezone
# pyrefly: ignore [missing-import]
from django.contrib.auth.models import User
# pyrefly: ignore [missing-import]
from django.urls import reverse
# pyrefly: ignore [missing-import]
from django.conf import settings
# pyrefly: ignore [missing-import]
from django.db import IntegrityError, transaction
from django.core.management import call_command
import threading
import time


from .models import Movie, Theater, Seat, Booking, PaymentOrder

class PaymentIntegrationTests(TestCase):
    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(username='testuser', password='testpassword')
        self.client = Client()
        self.client.login(username='testuser', password='testpassword')

        # Create test movie, theater, and seats
        self.movie = Movie.objects.create(
            name="Inception",
            rating=9.0,
            cast="Leonardo DiCaprio",
            description="A mind-bending thriller",
            image="movies/inception.jpg"
        )
        self.theater = Theater.objects.create(
            name="IMAX Screen 1",
            movie=self.movie,
            time=timezone.now() + timedelta(days=1),
            ticket_price=15.00
        )
        self.seat1 = Seat.objects.create(theater=self.theater, seat_number="A1", is_booked=False)
        self.seat2 = Seat.objects.create(theater=self.theater, seat_number="A2", is_booked=False)

    def test_book_seats_creates_pending_order(self):
        """Test that booking seats locks seats and redirects to checkout."""
        url = reverse('book_seats', args=[self.theater.id])
        response = self.client.post(url, {'seats': [self.seat1.id, self.seat2.id]})
        
        # Verify redirect to checkout page
        self.seat1.refresh_from_db()
        self.seat2.refresh_from_db()
        self.assertTrue(self.seat1.is_booked)
        self.assertTrue(self.seat2.is_booked)

        # Get the created PaymentOrder
        order = PaymentOrder.objects.filter(user=self.user).first()
        self.assertIsNotNone(order)
        self.assertEqual(order.status, PaymentOrder.Status.PENDING)
        self.assertEqual(order.amount, 30.00) # 2 seats * 15.00

        self.assertRedirects(response, reverse('checkout', args=[order.payment_id]))

    def test_idempotency_prevents_duplicate_orders(self):
        """Test that double submitting the exact same seats redirects to the same checkout session."""
        url = reverse('book_seats', args=[self.theater.id])
        
        # First booking request
        response1 = self.client.post(url, {'seats': [self.seat1.id]}, follow=True)
        order1 = PaymentOrder.objects.first()
        self.assertIsNotNone(order1)
        
        # Release the locked seat flag manually in memory just to test if the second request bypasses lock checks due to idempotency key
        self.seat1.is_booked = False
        self.seat1.save()

        # Second booking request with same seats
        response2 = self.client.post(url, {'seats': [self.seat1.id]})
        
        # Should redirect to the existing checkout session rather than creating a new one
        self.assertEqual(PaymentOrder.objects.count(), 1)
        self.assertRedirects(response2, reverse('checkout', args=[order1.payment_id]))

    def test_checkout_view_status_validation(self):
        """Test that checkout view only permits pending transactions."""
        order = PaymentOrder.objects.create(
            user=self.user,
            payment_id="MOCK_TEST_123",
            idempotency_key="key_123",
            amount=15.00,
            status=PaymentOrder.Status.COMPLETED
        )
        url = reverse('checkout', args=[order.payment_id])
        response = self.client.get(url)
        self.assertRedirects(response, reverse('profile'))

    def test_payment_cancellation_releases_seats(self):
        """Test that cancelling an order releases the locked seats."""
        order = PaymentOrder.objects.create(
            user=self.user,
            payment_id="MOCK_TEST_456",
            idempotency_key="key_456",
            amount=15.00,
            status=PaymentOrder.Status.PENDING
        )
        booking = Booking.objects.create(
            user=self.user,
            seat=self.seat1,
            movie=self.movie,
            theater=self.theater,
            payment_id=order.payment_id,
            status=Booking.Status.PENDING,
            payment_order=order
        )
        self.seat1.is_booked = True
        self.seat1.save()

        url = reverse('payment_cancel', args=[order.payment_id])
        response = self.client.get(url)
        
        order.refresh_from_db()
        booking.refresh_from_db()
        self.seat1.refresh_from_db()

        self.assertEqual(order.status, PaymentOrder.Status.CANCELLED)
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertFalse(self.seat1.is_booked)
        self.assertRedirects(response, reverse('movie_list'))

    def test_mock_webhook_signature_verification(self):
        """Test that the webhook rejects requests with invalid mock signatures."""
        url = reverse('payment_webhook')
        payload = json.dumps({"payment_id": "invalid", "status": "success"})
        
        # Send with invalid signature
        response = self.client.post(
            url,
            payload,
            content_type="application/json",
            HTTP_X_MOCK_SIGNATURE="badsignature"
        )
        self.assertEqual(response.status_code, 400)

    def test_webhook_success_and_idempotency(self):
        """Test that a valid successful webhook updates order and duplicate webhooks are processed idempotently."""
        order = PaymentOrder.objects.create(
            user=self.user,
            payment_id="MOCK_TEST_SUCCESS",
            idempotency_key="key_success",
            amount=15.00,
            status=PaymentOrder.Status.PENDING
        )
        booking = Booking.objects.create(
            user=self.user,
            seat=self.seat1,
            movie=self.movie,
            theater=self.theater,
            payment_id=order.payment_id,
            status=Booking.Status.PENDING,
            payment_order=order
        )
        self.seat1.is_booked = True
        self.seat1.save()

        # Generate valid mock webhook signature
        payload_data = {"payment_id": order.payment_id, "status": "success"}
        payload_bytes = json.dumps(payload_data).encode('utf-8')
        mock_secret = settings.MOCK_WEBHOOK_SECRET.encode('utf-8')
        signature = hmac.new(mock_secret, payload_bytes, hashlib.sha256).hexdigest()

        # Send webhook
        url = reverse('payment_webhook')
        response1 = self.client.post(
            url,
            payload_bytes,
            content_type="application/json",
            HTTP_X_MOCK_SIGNATURE=signature
        )
        self.assertEqual(response1.status_code, 200)
        
        order.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.COMPLETED)
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

        # Send duplicate webhook to verify idempotency (should return 200 and not crash or change state)
        response2 = self.client.post(
            url,
            payload_bytes,
            content_type="application/json",
            HTTP_X_MOCK_SIGNATURE=signature
        )
        self.assertEqual(response2.status_code, 200)
        self.assertIn("already processed", response2.content.decode())

    def test_webhook_failure_releases_seats(self):
        """Test that a payment failure webhook marks bookings as failed and releases seats."""
        order = PaymentOrder.objects.create(
            user=self.user,
            payment_id="MOCK_TEST_FAIL",
            idempotency_key="key_fail",
            amount=15.00,
            status=PaymentOrder.Status.PENDING
        )
        booking = Booking.objects.create(
            user=self.user,
            seat=self.seat1,
            movie=self.movie,
            theater=self.theater,
            payment_id=order.payment_id,
            status=Booking.Status.PENDING,
            payment_order=order
        )
        self.seat1.is_booked = True
        self.seat1.save()

        payload_data = {"payment_id": order.payment_id, "status": "failure"}
        payload_bytes = json.dumps(payload_data).encode('utf-8')
        mock_secret = settings.MOCK_WEBHOOK_SECRET.encode('utf-8')
        signature = hmac.new(mock_secret, payload_bytes, hashlib.sha256).hexdigest()

        url = reverse('payment_webhook')
        response = self.client.post(
            url,
            payload_bytes,
            content_type="application/json",
            HTTP_X_MOCK_SIGNATURE=signature
        )
        self.assertEqual(response.status_code, 200)

        order.refresh_from_db()
        booking.refresh_from_db()
        self.seat1.refresh_from_db()

        self.assertEqual(order.status, PaymentOrder.Status.FAILED)
        self.assertEqual(booking.status, Booking.Status.FAILED)
        self.assertFalse(self.seat1.is_booked)

    def test_expired_cleanup(self):
        """Test that older pending orders are expired and release seats."""
        order = PaymentOrder.objects.create(
            user=self.user,
            payment_id="MOCK_TEST_EXPIRED",
            idempotency_key="key_expired",
            amount=15.00,
            status=PaymentOrder.Status.PENDING
        )
        # Manually alter created_at to 15 minutes ago
        order.created_at = timezone.now() - timedelta(minutes=15)
        order.save()

        booking = Booking.objects.create(
            user=self.user,
            seat=self.seat1,
            movie=self.movie,
            theater=self.theater,
            payment_id=order.payment_id,
            status=Booking.Status.PENDING,
            payment_order=order
        )
        self.seat1.is_booked = True
        self.seat1.save()

        # Run views check (triggers cleanup_expired_bookings)
        from .views import cleanup_expired_bookings
        cleanup_expired_bookings()

        order.refresh_from_db()
        booking.refresh_from_db()
        self.seat1.refresh_from_db()

        self.assertEqual(order.status, PaymentOrder.Status.EXPIRED)
        self.assertEqual(booking.status, Booking.Status.FAILED)
        self.assertFalse(self.seat1.is_booked)

    def test_rebook_seats_after_expiry_or_cancellation(self):
        """Test that a user can book the same seats after a previous booking was expired or cancelled."""
        url = reverse('book_seats', args=[self.theater.id])
        self.client.login(username='testuser', password='testpassword')
        
        # 1. First booking
        response1 = self.client.post(url, {'seats': [self.seat1.id, self.seat2.id]})
        order1 = PaymentOrder.objects.filter(user=self.user).first()
        self.assertIsNotNone(order1)
        self.assertEqual(order1.status, PaymentOrder.Status.PENDING)
        
        # 2. Cancel the booking
        cancel_url = reverse('payment_cancel', args=[order1.payment_id])
        self.client.get(cancel_url)
        
        order1.refresh_from_db()
        self.assertEqual(order1.status, PaymentOrder.Status.CANCELLED)
        
        # 3. Second booking for the exact same seats (should succeed!)
        response2 = self.client.post(url, {'seats': [self.seat1.id, self.seat2.id]})
        
        # Verify a new order was created and we did not crash with UNIQUE constraint error
        order2 = PaymentOrder.objects.filter(user=self.user).exclude(id=order1.id).first()
        self.assertIsNotNone(order2)
        self.assertEqual(order2.status, PaymentOrder.Status.PENDING)

    def test_enqueue_email_for_user_without_email(self):
        """Test that enqueue_booking_confirmation_email works for a user without an email address."""
        from .email import enqueue_booking_confirmation_email
        from .models import EmailLog
        
        # Modify self.user to have no email address
        self.user.email = ''
        self.user.save()
        
        booking = Booking.objects.create(
            user=self.user,
            seat=self.seat1,
            movie=self.movie,
            theater=self.theater,
            status=Booking.Status.PENDING
        )
        
        # Enqueue the confirmation email - should not crash
        res = enqueue_booking_confirmation_email([booking])
        self.assertIsNone(res)
        
        # Verify that an EmailLog was created with a FAILED status and appropriate error message
        log = EmailLog.objects.filter(user=self.user).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, EmailLog.Status.FAILED)
        self.assertEqual(log.email_address, '')
        self.assertEqual(log.error_message, 'User has no email address')




class SeatConcurrencyAndSchedulerTests(TransactionTestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username='user1', password='password')
        self.user2 = User.objects.create_user(username='user2', password='password')
        self.movie = Movie.objects.create(
            name="Inception Concurrency",
            rating=9.0,
            cast="Leo",
            image="movies/concurrency.jpg"
        )
        self.theater = Theater.objects.create(
            name="Concurrency Screen",
            movie=self.movie,
            time=timezone.now() + timedelta(days=1),
            ticket_price=10.00
        )
        self.seat = Seat.objects.create(theater=self.theater, seat_number="C1", is_booked=False)

    def test_scheduler_releases_expired_reservations(self):
        """Test that the management command releases expired orders (>2m) but leaves active ones (<2m)."""
        # 1. Expired order (3 minutes ago)
        expired_order = PaymentOrder.objects.create(
            user=self.user1,
            payment_id="EXPIRED_SCHEDULER_TEST",
            idempotency_key="key_expired_sched",
            amount=10.00,
            status=PaymentOrder.Status.PENDING
        )
        expired_order.created_at = timezone.now() - timedelta(minutes=3)
        expired_order.save()
        
        expired_booking = Booking.objects.create(
            user=self.user1,
            seat=self.seat,
            movie=self.movie,
            theater=self.theater,
            payment_id=expired_order.payment_id,
            status=Booking.Status.PENDING,
            payment_order=expired_order
        )
        self.seat.is_booked = True
        self.seat.save()

        # 2. Active order (30 seconds ago)
        active_seat = Seat.objects.create(theater=self.theater, seat_number="C2", is_booked=True)
        active_order = PaymentOrder.objects.create(
            user=self.user2,
            payment_id="ACTIVE_SCHEDULER_TEST",
            idempotency_key="key_active_sched",
            amount=10.00,
            status=PaymentOrder.Status.PENDING
        )
        active_booking = Booking.objects.create(
            user=self.user2,
            seat=active_seat,
            movie=self.movie,
            theater=self.theater,
            payment_id=active_order.payment_id,
            status=Booking.Status.PENDING,
            payment_order=active_order
        )

        # Run the background scheduler command programmatically
        call_command('release_expired_bookings')

        # Refresh from db
        expired_order.refresh_from_db()
        expired_booking.refresh_from_db()
        self.seat.refresh_from_db()

        active_order.refresh_from_db()
        active_booking.refresh_from_db()
        active_seat.refresh_from_db()

        # Assert expired order was released
        self.assertEqual(expired_order.status, PaymentOrder.Status.EXPIRED)
        self.assertEqual(expired_booking.status, Booking.Status.FAILED)
        self.assertFalse(self.seat.is_booked)

        # Assert active order remains unchanged
        self.assertEqual(active_order.status, PaymentOrder.Status.PENDING)
        self.assertEqual(active_booking.status, Booking.Status.PENDING)
        self.assertTrue(active_seat.is_booked)

    def test_concurrent_booking_race_condition(self):
        """Verify that concurrent booking requests for the same seat result in only one success."""
        errors = []
        successes = []
        
        def attempt_booking(user, seat_id):
            from django.db import connection
            try:
                with transaction.atomic():
                    # Acquire lock
                    locked_seat = Seat.objects.select_for_update().get(id=seat_id)
                    if locked_seat.is_booked:
                        raise IntegrityError("Seat already booked")
                    
                    # Simulate some latency to force overlapping transactions
                    time.sleep(0.2)
                    
                    # Perform booking
                    payment_id = f"CONC_PAY_{user.username}"
                    order = PaymentOrder.objects.create(
                        user=user,
                        payment_id=payment_id,
                        idempotency_key=f"key_{user.username}_{seat_id}",
                        amount=10.00,
                        status=PaymentOrder.Status.PENDING
                    )
                    Booking.objects.create(
                        user=user,
                        seat=locked_seat,
                        movie=self.movie,
                        theater=self.theater,
                        payment_id=payment_id,
                        status=Booking.Status.PENDING,
                        payment_order=order
                    )
                    locked_seat.is_booked = True
                    locked_seat.save(update_fields=['is_booked'])
                successes.append(user.username)
            except Exception as e:
                errors.append(str(e))
            finally:
                connection.close()

        # Start two threads competing for the same seat
        t1 = threading.Thread(target=attempt_booking, args=(self.user1, self.seat.id))
        t2 = threading.Thread(target=attempt_booking, args=(self.user2, self.seat.id))
        
        t1.start()
        # Delay slightly to ensure t1 starts and locks first
        time.sleep(0.05)
        t2.start()
        
        t1.join()
        t2.join()
        
        # Verify exactly one thread successfully booked the seat
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        
        # Verify database state matches the successful thread
        self.seat.refresh_from_db()
        self.assertTrue(self.seat.is_booked)
        
        # Verify that the booking corresponds to the successful user
        booking = Booking.objects.get(seat=self.seat)
        self.assertEqual(booking.user.username, successes[0])
        self.assertEqual(booking.status, Booking.Status.PENDING)

    def test_invalid_seat_ids_validation(self):
        """Test that booking with a mix of valid and invalid seat IDs raises error and does not create orders."""
        url = reverse('book_seats', args=[self.theater.id])
        self.client.force_login(self.user1)
        
        # Post one valid seat and one invalid seat (ID 9999)
        response = self.client.post(url, {'seats': [self.seat.id, 9999]})
        
        # Assert database was rolled back and seat remains unbooked
        self.seat.refresh_from_db()
        self.assertFalse(self.seat.is_booked)
        
        # Assert no orders or bookings were created
        self.assertEqual(PaymentOrder.objects.filter(user=self.user1).count(), 0)
        self.assertEqual(Booking.objects.filter(user=self.user1).count(), 0)
        
        # Assert the error message is present in the rendered HTML response
        self.assertIn("One or more selected seats are invalid.", response.content.decode())

    def test_background_scheduler_thread_integration(self):
        """Test that starting the background scheduler thread automatically releases expired seats."""
        expired_order = PaymentOrder.objects.create(
            user=self.user1,
            payment_id="THREAD_SCHEDULER_TEST",
            idempotency_key="key_thread_sched",
            amount=10.00,
            status=PaymentOrder.Status.PENDING
        )
        expired_order.created_at = timezone.now() - timedelta(minutes=3)
        expired_order.save()
        
        expired_booking = Booking.objects.create(
            user=self.user1,
            seat=self.seat,
            movie=self.movie,
            theater=self.theater,
            payment_id=expired_order.payment_id,
            status=Booking.Status.PENDING,
            payment_order=expired_order
        )
        self.seat.is_booked = True
        self.seat.save()

        # Start the background scheduler thread with a 0.1s loop interval
        from .scheduler import run_scheduler
        import threading
        
        thread = threading.Thread(target=run_scheduler, args=(0.1,), daemon=True)
        thread.start()
        
        # Wait slightly to let the thread complete its first iteration
        time.sleep(0.3)
        
        # Refresh and verify expired resources were released
        expired_order.refresh_from_db()
        expired_booking.refresh_from_db()
        self.seat.refresh_from_db()
        
        self.assertEqual(expired_order.status, PaymentOrder.Status.EXPIRED)
        self.assertEqual(expired_booking.status, Booking.Status.FAILED)
        self.assertFalse(self.seat.is_booked)

