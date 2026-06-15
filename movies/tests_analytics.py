from datetime import timedelta
# pyrefly: ignore [missing-import]
from django.test import TestCase, Client
# pyrefly: ignore [missing-import]
from django.contrib.auth.models import User
# pyrefly: ignore [missing-import]
from django.urls import reverse
# pyrefly: ignore [missing-import]
from django.core.cache import cache
from django.utils import timezone

from movies.models import Movie, Theater, Seat, Booking, PaymentOrder


class AdminAnalyticsTests(TestCase):
    def setUp(self):
        # Clear cache before each test
        cache.clear()
        
        # Create standard users and admin user
        self.client = Client()
        self.regular_user = User.objects.create_user(username='regular', password='password123')
        
        self.admin_user = User.objects.create_user(username='admin_test', password='password123')
        self.admin_test = self.admin_user # Alias
        self.admin_user.is_staff = True
        self.admin_user.save()

        # Seed minimal database objects for API response validity
        self.movie = Movie.objects.create(
            name="Analytics Test Movie",
            rating=8.5,
            cast="Test Cast",
            image="movies/test.jpg"
        )
        self.theater = Theater.objects.create(
            name="Analytics Theater",
            movie=self.movie,
            time=timezone.now(),
            ticket_price=10.00
        )
        self.seat = Seat.objects.create(theater=self.theater, seat_number="Z1", is_booked=True)
        
        self.order = PaymentOrder.objects.create(
            user=self.regular_user,
            payment_id="ANALYTICS_PAY_1",
            idempotency_key="key_analytics_test",
            amount=10.00,
            status=PaymentOrder.Status.COMPLETED
        )
        self.booking = Booking.objects.create(
            user=self.regular_user,
            seat=self.seat,
            movie=self.movie,
            theater=self.theater,
            payment_id="ANALYTICS_PAY_1",
            status=Booking.Status.CONFIRMED,
            payment_order=self.order
        )

    def test_unauthenticated_access_blocked(self):
        """Verify that anonymous users are redirected to login."""
        url_dashboard = reverse('admin_analytics')
        url_api = reverse('admin_analytics_api')
        
        response_dash = self.client.get(url_dashboard)
        response_api = self.client.get(url_api)
        
        # Django staff_member_required redirects to login with next parameter
        self.assertEqual(response_dash.status_code, 302)
        self.assertIn('/login/', response_dash.url)
        self.assertEqual(response_api.status_code, 302)
        self.assertIn('/login/', response_api.url)

    def test_regular_user_access_blocked(self):
        """Verify that regular authenticated (non-staff) users are redirected to login."""
        self.client.login(username='regular', password='password123')
        
        url_dashboard = reverse('admin_analytics')
        url_api = reverse('admin_analytics_api')
        
        response_dash = self.client.get(url_dashboard)
        response_api = self.client.get(url_api)
        
        self.assertEqual(response_dash.status_code, 302)
        self.assertEqual(response_api.status_code, 302)

    def test_admin_user_access_allowed(self):
        """Verify that staff/admin users can load the dashboard and API successfully."""
        self.client.login(username='admin_test', password='password123')
        
        url_dashboard = reverse('admin_analytics')
        url_api = reverse('admin_analytics_api')
        
        response_dash = self.client.get(url_dashboard)
        response_api = self.client.get(url_api)
        
        self.assertEqual(response_dash.status_code, 200)
        self.assertEqual(response_api.status_code, 200)

    def test_analytics_api_aggregations(self):
        """Verify that the API returns correct aggregates calculated from the database."""
        self.client.login(username='admin_test', password='password123')
        
        url_api = reverse('admin_analytics_api')
        response = self.client.get(url_api)
        data = response.json()
        
        # Revenue should equal order amounts
        self.assertEqual(data['revenue']['daily'], 10.0)
        self.assertEqual(data['revenue']['weekly'], 10.0)
        self.assertEqual(data['revenue']['monthly'], 10.0)
        
        # Popular movies should include our movie name
        self.assertEqual(data['popular_movies'][0]['movie__name'], "Analytics Test Movie")
        self.assertEqual(data['popular_movies'][0]['booking_count'], 1)
        
        # Busiest theaters occupancy rate should be calculated
        self.assertEqual(data['busiest_theaters'][0]['name'], "Analytics Theater")
        self.assertEqual(data['busiest_theaters'][0]['occupancy_rate'], 100.0)
        
        # Source should indicate it read from database on first request
        self.assertEqual(data['source'], "Database Query")

    def test_analytics_api_caching(self):
        """Verify that subsequent requests are served from the cache (reducing DB queries)."""
        self.client.login(username='admin_test', password='password123')
        url_api = reverse('admin_analytics_api')
        
        # First request (fetches from database and populates cache)
        response1 = self.client.get(url_api)
        data1 = response1.json()
        self.assertEqual(data1['source'], "Database Query")
        
        # Introduce a modification in the database that would change the statistics
        # (Create another revenue order)
        PaymentOrder.objects.create(
            user=self.regular_user,
            payment_id="ANALYTICS_PAY_2",
            idempotency_key="key_analytics_test_2",
            amount=50.00,
            status=PaymentOrder.Status.COMPLETED
        )
        
        # Second request (should pull from cache and not reflect the changes yet)
        response2 = self.client.get(url_api)
        data2 = response2.json()
        
        self.assertEqual(data2['source'], "Cache")
        self.assertEqual(data2['revenue']['daily'], 10.0) # Original value cached
        
        # Test refresh=true parameter (should bypass cache and get database query)
        response_refresh = self.client.get(url_api + '?refresh=true')
        data_refresh = response_refresh.json()
        self.assertEqual(data_refresh['source'], "Database Query")
        self.assertEqual(data_refresh['revenue']['daily'], 60.0) # Reflects new value
        
        # Now regular request should load from the newly cached value (which is 60)
        response_cache = self.client.get(url_api)
        self.assertEqual(response_cache.json()['source'], "Cache")
        self.assertEqual(response_cache.json()['revenue']['daily'], 60.0)
