from datetime import timedelta
from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from django.utils import timezone
from django.contrib.auth.models import User
from django.core import mail
from movies.models import Genre, Language, Movie, Theater, Seat, PaymentOrder, Booking, EmailQueueItem

class ManagementCommandTests(TestCase):
    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(username='test_cmd_user', password='password123', email='test@example.com')
        
    def test_seed_catalog_command(self):
        """Test the seed_catalog command clears and seeds successfully."""
        out = StringIO()
        call_command('seed_catalog', count=5, stdout=out)
        
        # Check that genres, languages, and movies are created
        self.assertTrue(Genre.objects.exists())
        self.assertTrue(Language.objects.exists())
        self.assertGreaterEqual(Movie.objects.count(), 4) # 4 specific movies + random ones
        
        # Verify specific movies are seeded
        avengers = Movie.objects.filter(name='Avengers').first()
        self.assertIsNotNone(avengers)
        self.assertTrue(avengers.genres.filter(name='Action').exists())
        
        # Test clear parameter
        out_clear = StringIO()
        call_command('seed_catalog', count=2, clear=True, stdout=out_clear)
        self.assertGreaterEqual(Movie.objects.count(), 2)

    def test_release_expired_bookings_command(self):
        """Test the release_expired_bookings command works correctly."""
        movie = Movie.objects.create(name="Test Movie", rating=8.0, cast="Cast")
        theater = Theater.objects.create(name="Test Theater", movie=movie, time=timezone.now(), ticket_price=10.0)
        seat = Seat.objects.create(theater=theater, seat_number="E1", is_booked=True)
        
        # Create order that is expired (older than 2 minutes)
        expired_time = timezone.now() - timedelta(minutes=3)
        order = PaymentOrder.objects.create(
            user=self.user,
            payment_id="TEST_EXPIRED_123",
            idempotency_key="key_expired_123",
            amount=10.00,
            status=PaymentOrder.Status.PENDING
        )
        # Bypass auto_now_add using update
        PaymentOrder.objects.filter(id=order.id).update(created_at=expired_time)
        
        booking = Booking.objects.create(
            user=self.user,
            seat=seat,
            movie=movie,
            theater=theater,
            payment_id=order.payment_id,
            status=Booking.Status.PENDING,
            payment_order=order
        )
        
        # Verify seat is booked before command runs
        self.assertEqual(Seat.objects.filter(id=seat.id, is_booked=True).count(), 1)
        
        # Run release expired bookings command
        out = StringIO()
        call_command('release_expired_bookings', stdout=out)
        
        # Verify updates
        order.refresh_from_db()
        booking.refresh_from_db()
        seat.refresh_from_db()
        
        self.assertEqual(order.status, PaymentOrder.Status.EXPIRED)
        self.assertEqual(booking.status, Booking.Status.FAILED)
        self.assertFalse(seat.is_booked)

    def test_process_email_queue_command(self):
        """Test that process_email_queue processes pending items."""
        # Create pending queue item
        queue_item = EmailQueueItem.objects.create(
            user=self.user,
            to_email="test@example.com",
            subject="Test Subject",
            template_name="emails/booking_confirmation.txt",
            payload={
                "user_name": "Test User",
                "movie_name": "Avengers",
                "theater_name": "IMAX",
                "seat_numbers": ["A1"],
                "show_date": "Today",
                "show_time_formatted": "9 PM",
                "support_email": "support@example.com"
            }
        )
        
        # Clear outbox
        mail.outbox = []
        
        # Run process_email_queue command
        out = StringIO()
        call_command('process_email_queue', stdout=out)
        
        # Refresh and verify
        queue_item.refresh_from_db()
        self.assertEqual(queue_item.status, EmailQueueItem.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Test Subject")
