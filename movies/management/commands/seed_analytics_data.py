
import random
import uuid
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from movies.models import Movie, Theater, Seat, Booking, PaymentOrder


class Command(BaseCommand):
    """
    Seed genres, languages, movies, theaters, seats, and 50,000+ bookings.
    
    This is used to test the optimizations of the admin analytics dashboard.
    
    Usage:
        python manage.py seed_analytics_data
    """
    help = 'Bulk seed database with 50,000+ bookings and an admin account for analytics dashboard load testing.'

    def handle(self, *args, **options):
        self.stdout.write("Starting database seeding for analytics testing...")
        
        # 1. Ensure admin superuser exists
        admin_user, created = User.objects.get_or_create(username='admin')
        if created or not admin_user.is_staff:
            admin_user.set_password('SecureAdminPassword123!')
            admin_user.is_superuser = True
            admin_user.is_staff = True
            admin_user.save()
            self.stdout.write(self.style.SUCCESS("Created admin superuser (admin / SecureAdminPassword123!)"))
        else:
            self.stdout.write("Admin superuser already exists.")

        # 2. Ensure we have users
        users = []
        for i in range(50):
            username = f"test_user_{i}"
            user, created = User.objects.get_or_create(username=username)
            if created:
                user.set_password("Password123!")
                user.save()
            users.append(user)
        self.stdout.write(f"Ensured {len(users)} test users exist.")

        # 3. Ensure we have movies
        movies = list(Movie.objects.all())
        if len(movies) < 5:
            self.stdout.write(self.style.WARNING("Not enough movies in catalog. Running seed_catalog first..."))
            from django.core.management import call_command
            call_command('seed_catalog', count=15)
            movies = list(Movie.objects.all())

        # 4. Create Theaters
        self.stdout.write("Creating theaters...")
        theaters = []
        now = timezone.now()
        for i in range(200):
            theater = Theater(
                name=f"Grand Cinema Screen {i+1}",
                movie=random.choice(movies),
                time=now - timedelta(days=random.randint(-5, 30)),
                ticket_price=12.50
            )
            theaters.append(theater)
        Theater.objects.bulk_create(theaters)
        # Fetch the newly created 200 theaters with their movies
        theaters = list(Theater.objects.select_related('movie').order_by('-id')[:200])
        self.stdout.write(f"Created {len(theaters)} theaters.")

        # 5. Create Seats (250 seats per theater = 50,000 seats total)
        self.stdout.write("Creating 50,000+ seats...")
        seats = []
        for theater in theaters:
            for row in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']: # 10 rows
                for col in range(1, 26): # 25 seats per row
                    seat = Seat(
                        theater=theater,
                        seat_number=f"{row}{col}",
                        is_booked=False
                    )
                    seats.append(seat)
        
        # Bulk create seats in batches of 5000 to prevent SQL length issues
        Seat.objects.bulk_create(seats, batch_size=5000)
        
        # Retrieve all seeded seats for these theaters
        theater_ids = [t.id for t in theaters]
        all_seats = list(Seat.objects.filter(theater_id__in=theater_ids))
        self.stdout.write(f"Created {len(all_seats)} seats.")

        # 6. Generate Bookings and PaymentOrders
        self.stdout.write("Generating 50,000 bookings and orders...")
        
        # Shuffle seats to make the booking random
        random.shuffle(all_seats)
        
        # Take exactly 50,000 seats to book (which is all of them)
        seats_to_book = all_seats[:50000]
        
        orders_batch = []
        bookings_batch = []
        
        # Create a mapping of theater ID to theater object for memory lookup to prevent N+1 queries
        theater_map = {t.id: t for t in theaters}
        
        # Distribute seats into orders of size 1 to 4
        seat_index = 0
        order_counter = 0
        
        # Status distribution: 82% completed, 8% failed, 5% cancelled, 5% expired
        statuses = [
            (PaymentOrder.Status.COMPLETED, Booking.Status.CONFIRMED, 0.82),
            (PaymentOrder.Status.FAILED, Booking.Status.FAILED, 0.08),
            (PaymentOrder.Status.CANCELLED, Booking.Status.CANCELLED, 0.05),
            (PaymentOrder.Status.EXPIRED, Booking.Status.FAILED, 0.05),
        ]
        
        # Generate random dates over last 30 days with weighted peak hours
        date_pool = []
        for d in range(30):
            for h in range(24):
                # Peak booking hours (e.g. 18:00 - 22:00) get higher weights
                weight = 1
                if 18 <= h <= 22:
                    weight = 4
                elif 12 <= h <= 17:
                    weight = 2
                
                for _ in range(weight):
                    date_pool.append(
                        now - timedelta(days=d) - timedelta(hours=now.hour - h) - timedelta(minutes=random.randint(0, 59))
                    )
        
        # Create orders and bookings
        while seat_index < len(seats_to_book):
            order_size = min(random.randint(1, 4), len(seats_to_book) - seat_index)
            order_seats = seats_to_book[seat_index:seat_index+order_size]
            seat_index += order_size
            
            user = random.choice(users)
            order_date = random.choice(date_pool)
            
            # Determine order status
            rand_val = random.random()
            cum_prob = 0
            order_status = PaymentOrder.Status.COMPLETED
            booking_status = Booking.Status.CONFIRMED
            for o_st, b_st, prob in statuses:
                cum_prob += prob
                if rand_val <= cum_prob:
                    order_status = o_st
                    booking_status = b_st
                    break
                    
            theater = theater_map[order_seats[0].theater_id]
            amount = order_size * theater.ticket_price
            payment_id = f"MOCK_PAY_{uuid.uuid4().hex.upper()}"
            idempotency_key = f"seed_{payment_id}_{order_counter}"
            
            order = PaymentOrder(
                user=user,
                payment_id=payment_id,
                idempotency_key=idempotency_key,
                amount=amount,
                status=order_status,
                created_at=order_date
            )
            orders_batch.append(order)
            order_counter += 1
            
            for seat in order_seats:
                # Update seat is_booked status in memory
                if order_status in [PaymentOrder.Status.COMPLETED, PaymentOrder.Status.PENDING]:
                    seat.is_booked = True
                
                booking = Booking(
                    user=user,
                    seat=seat,
                    movie=theater.movie,
                    theater=theater,
                    payment_id=payment_id,
                    status=booking_status,
                    booked_at=order_date
                )
                bookings_batch.append((booking, order))
                
        # Bulk create PaymentOrders in batches
        self.stdout.write(f"Bulk saving {len(orders_batch)} PaymentOrders...")
        PaymentOrder.objects.bulk_create(orders_batch, batch_size=5000)
        
        # Fetch payment orders from database to map their IDs
        self.stdout.write("Mapping database keys...")
        all_db_orders = list(PaymentOrder.objects.filter(idempotency_key__startswith="seed_"))
        id_to_order_map = {o.idempotency_key: o for o in all_db_orders}
        
        # Link bookings to payment_order
        final_bookings = []
        for booking, order_obj in bookings_batch:
            order_from_db = id_to_order_map.get(order_obj.idempotency_key)
            if order_from_db:
                booking.payment_order_id = order_from_db.id
                final_bookings.append(booking)
        
        self.stdout.write(f"Bulk saving {len(final_bookings)} Bookings...")
        Booking.objects.bulk_create(final_bookings, batch_size=5000)
        
        # Bulk update seat is_booked statuses
        self.stdout.write("Updating seat booking statuses...")
        seats_to_update = [s for s in seats_to_book if s.is_booked]
        Seat.objects.bulk_update(seats_to_update, ['is_booked'], batch_size=5000)
        
        self.stdout.write(self.style.SUCCESS(
            f"Successfully seeded {len(orders_batch)} orders, {len(final_bookings)} bookings, "
            f"and {len(seats_to_update)} booked seats!"
        ))
