import uuid
import hmac
import hashlib
import json
import stripe
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, HttpResponseBadRequest, Http404
from django.test import RequestFactory

from .filters import (
    MovieFilterParams,
    filter_movies,
    get_genre_facets,
    get_language_facets,
)
from .models import Movie, Theater, Seat, Booking, PaymentOrder
from .email import enqueue_booking_confirmation_email

MOVIES_PER_PAGE = 12


def cleanup_expired_bookings():
    """
    Utility task that finds pending payment orders older than 10 minutes
    and releases the held seats and marks bookings/orders as expired.
    """
    try:
        threshold = timezone.now() - timedelta(minutes=2)
        expired_orders = PaymentOrder.objects.filter(status=PaymentOrder.Status.PENDING, created_at__lt=threshold)
        for order in expired_orders:
            with transaction.atomic():
                try:
                    order = PaymentOrder.objects.select_for_update().get(id=order.id)
                    if order.status == PaymentOrder.Status.PENDING:
                        order.status = PaymentOrder.Status.EXPIRED
                        # Release the idempotency_key so the same seats can be reserved again
                        order.idempotency_key = f"{order.idempotency_key}_expired_{order.id}"
                        order.save(update_fields=['status', 'idempotency_key'])
                        
                        # Release associated seats and bookings
                        bookings = order.bookings.all()
                        seat_ids = [b.seat_id for b in bookings]
                        bookings.update(status=Booking.Status.FAILED)
                        Seat.objects.filter(id__in=seat_ids).update(is_booked=False)
                except PaymentOrder.DoesNotExist:
                    continue
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to cleanup expired bookings: {e}")



def movie_list(request):
    cleanup_expired_bookings()
    params = MovieFilterParams.from_request(request)

    filtered_movies = filter_movies(params)
    paginator = Paginator(filtered_movies, MOVIES_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    genres = get_genre_facets(params.search, params.language_ids)
    languages = get_language_facets(params.search, params.genre_ids)

    context = {
        'movies': page_obj,
        'page_obj': page_obj,
        'genres': genres,
        'languages': languages,
        'selected_genre_ids': list(params.genre_ids),
        'selected_language_ids': list(params.language_ids),
        'sort_option': params.sort,
        'search_query': params.search,
        'filters_active': params.is_active,
        'total_results': paginator.count,
    }
    return render(request, 'movies/movie_list.html', context)


def theater_list(request, movie_id):
    cleanup_expired_bookings()
    movie = get_object_or_404(Movie, id=movie_id)
    theater = Theater.objects.filter(movie=movie)
    return render(request, 'movies/theater_list.html', {'movie': movie, 'theaters': theater})


def _seat_selection_context(theater, seats, error=None):
    # Natural sort key: sort by row letter alphabetically, then by seat number numerically
    def natural_sort_key(seat):
        num = seat.seat_number
        if not num:
            return ('', 0)
        row = num[0].upper()
        # Extract digits from the rest of the string
        digits = ''.join(c for c in num[1:] if c.isdigit())
        val = int(digits) if digits else 0
        return (row, val)
        
    sorted_seats = sorted(seats, key=natural_sort_key)
    
    # Attach row and label attributes dynamically for template grouping
    for seat in sorted_seats:
        seat.row_letter = seat.seat_number[0].upper() if seat.seat_number else ''
        seat.number_label = seat.seat_number[1:] if seat.seat_number else ''
        
    return {
        'theater': theater,
        'seats': sorted_seats,
        'error': error,
    }



@login_required(login_url='/login/')
def book_seats(request, theater_id):
    cleanup_expired_bookings()
    theater = get_object_or_404(Theater, id=theater_id)
    if request.method == 'POST':
        selected_seats = request.POST.getlist('seats')
        if not selected_seats:
            seats = Seat.objects.filter(theater=theater)
            return render(
                request,
                'movies/seat_selection.html',
                _seat_selection_context(theater, seats, 'Please select at least one seat.'),
            )

        # 1. Create unique idempotency key based on user, theater and selected seats
        sorted_seats = sorted([int(s) for s in selected_seats])
        seats_str = ",".join(str(s) for s in sorted_seats)
        idempotency_key = f"user_{request.user.id}_theater_{theater_id}_seats_{seats_str}"

        # 2. Check for duplicate request / active payment order
        existing_order = PaymentOrder.objects.filter(
            idempotency_key=idempotency_key
        ).exclude(status__in=[PaymentOrder.Status.FAILED, PaymentOrder.Status.EXPIRED, PaymentOrder.Status.CANCELLED]).first()

        if existing_order:
            if existing_order.status == PaymentOrder.Status.COMPLETED:
                messages.success(request, 'Tickets already booked successfully for these seats.')
                return redirect('profile')
            # If pending, redirect them to the existing checkout session
            return redirect('checkout', payment_id=existing_order.payment_id)

        # 3. Create new payment order & book seats inside atomic transaction
        error_seats = []
        booked_bookings = []
        
        try:
            with transaction.atomic():
                # Lock the seats row in the database immediately using list() to prevent concurrent double-booking
                seats = list(Seat.objects.select_for_update().filter(id__in=selected_seats, theater=theater))
                
                # Verify that all selected seats exist and belong to this theater
                if len(seats) != len(selected_seats):
                    raise IntegrityError("One or more selected seats are invalid.")
                
                # Double-check availability
                for seat in seats:
                    if seat.is_booked:
                        error_seats.append(seat.seat_number)
                
                if error_seats:
                    raise IntegrityError("Some seats are already booked.")

                amount = len(seats) * theater.ticket_price
                
                # Setup Stripe public/secret
                stripe_enabled = bool(settings.STRIPE_SECRET_KEY)
                payment_id = f"MOCK_PAY_{uuid.uuid4().hex.upper()}"

                if stripe_enabled:
                    try:
                        stripe.api_key = settings.STRIPE_SECRET_KEY
                        intent = stripe.PaymentIntent.create(
                            amount=int(amount * 100), # cents
                            currency="usd",
                            idempotency_key=idempotency_key,
                            metadata={
                                "user_id": request.user.id,
                                "theater_id": theater_id,
                                "seat_ids": seats_str
                            }
                        )
                        payment_id = intent.id
                    except stripe.error.StripeError as e:
                        # Fallback to mock on stripe API failure to prevent blocking the checkout flow
                        messages.warning(request, f"Payment gateway issue: {str(e)}. Switched to simulation mode.")
                        stripe_enabled = False

                # Create PaymentOrder
                order = PaymentOrder.objects.create(
                    user=request.user,
                    payment_id=payment_id,
                    idempotency_key=idempotency_key,
                    amount=amount,
                    status=PaymentOrder.Status.PENDING
                )

                # Create Booking for each seat linked to the order
                for seat in seats:
                    booking = Booking.objects.create(
                        user=request.user,
                        seat=seat,
                        movie=theater.movie,
                        theater=theater,
                        payment_id=payment_id,
                        status=Booking.Status.PENDING,
                        payment_order=order
                    )
                    seat.is_booked = True
                    seat.save(update_fields=['is_booked'])
                    booked_bookings.append(booking)

        except (IntegrityError, Exception) as e:
            # If any failure occurs, transaction is rolled back automatically
            seats = Seat.objects.filter(theater=theater)
            error_message = f"Could not book: {', '.join(error_seats) if error_seats else str(e)}."
            return render(
                request,
                'movies/seat_selection.html',
                _seat_selection_context(theater, seats, error_message),
            )

        return redirect('checkout', payment_id=payment_id)

    seats = Seat.objects.filter(theater=theater)
    return render(request, 'movies/seat_selection.html', _seat_selection_context(theater, seats))


@login_required(login_url='/login/')
def checkout(request, payment_id):
    cleanup_expired_bookings()
    order = get_object_or_404(PaymentOrder, payment_id=payment_id, user=request.user)
    
    if order.status != PaymentOrder.Status.PENDING:
        if order.status == PaymentOrder.Status.COMPLETED:
            messages.success(request, "This payment was already completed successfully.")
        else:
            messages.error(request, f"This checkout session is no longer active (Status: {order.status}).")
        return redirect('profile')

    stripe_enabled = bool(settings.STRIPE_SECRET_KEY)
    client_secret = ""
    
    if stripe_enabled:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            intent = stripe.PaymentIntent.retrieve(payment_id)
            client_secret = intent.client_secret
        except stripe.error.StripeError:
            stripe_enabled = False

    context = {
        'order': order,
        'stripe_enabled': stripe_enabled,
        'stripe_public_key': settings.STRIPE_PUBLIC_KEY,
        'stripe_client_secret': client_secret,
    }
    return render(request, 'movies/checkout.html', context)


@login_required(login_url='/login/')
def payment_cancel(request, payment_id):
    order = get_object_or_404(PaymentOrder, payment_id=payment_id, user=request.user)
    
    if order.status == PaymentOrder.Status.PENDING:
        with transaction.atomic():
            order.status = PaymentOrder.Status.CANCELLED
            order.idempotency_key = f"{order.idempotency_key}_cancelled_{order.id}"
            order.save(update_fields=['status', 'idempotency_key'])
            
            # Release seats and update bookings
            bookings = order.bookings.all()
            seat_ids = [b.seat_id for b in bookings]
            bookings.update(status=Booking.Status.CANCELLED)
            Seat.objects.filter(id__in=seat_ids).update(is_booked=False)
            
        messages.info(request, "Your booking was cancelled, and the selected seats have been released.")
    
    return redirect('movie_list')


@csrf_exempt
def payment_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    mock_sig = request.META.get('HTTP_X_MOCK_SIGNATURE')

    event_type = None
    payment_id = None
    success = False

    # 1. Validate signature and extract payment intent details
    if settings.STRIPE_SECRET_KEY and settings.STRIPE_WEBHOOK_SECRET and sig_header:
        # Real Stripe validation
        try:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
            event_type = event['type']
            payment_intent = event['data']['object']
            payment_id = payment_intent['id']
            
            if event_type == 'payment_intent.succeeded':
                success = True
            elif event_type == 'payment_intent.payment_failed':
                success = False
            else:
                return HttpResponse(status=200)  # Ignore other events
        except (ValueError, stripe.error.SignatureVerificationError):
            return HttpResponseBadRequest("Invalid Stripe signature")
    elif mock_sig:
        # Mock Signature Validation
        mock_secret = settings.MOCK_WEBHOOK_SECRET.encode('utf-8')
        computed_sig = hmac.new(mock_secret, payload, hashlib.sha256).hexdigest()
        
        if not hmac.compare_digest(computed_sig, mock_sig):
            return HttpResponseBadRequest("Invalid Mock webhook signature")
            
        try:
            data = json.loads(payload.decode('utf-8'))
            payment_id = data.get('payment_id')
            success = data.get('status') == 'success'
        except (ValueError, KeyError):
            return HttpResponseBadRequest("Invalid payload format")
    else:
        return HttpResponseBadRequest("Missing webhook signature")

    # 2. Process order status update with idempotency protection
    try:
        with transaction.atomic():
            # select_for_update locks the order to prevent concurrent updates from duplicate webhooks
            order = PaymentOrder.objects.select_for_update().get(payment_id=payment_id)
            
            if success:
                if order.status == PaymentOrder.Status.COMPLETED:
                    # Already processed: return 200 OK immediately (idempotency check)
                    return HttpResponse("Webhook already processed (Idempotent)", status=200)
                
                # Complete the order and bookings
                order.status = PaymentOrder.Status.COMPLETED
                order.save(update_fields=['status'])
                
                bookings = list(order.bookings.all())
                order.bookings.all().update(status=Booking.Status.CONFIRMED)
                
                # Send confirmation email
                transaction.on_commit(lambda: enqueue_booking_confirmation_email(bookings))
            else:
                if order.status == PaymentOrder.Status.FAILED:
                    return HttpResponse("Webhook already processed (Idempotent)", status=200)
                    
                # Fail the order, update bookings, and release seats
                order.status = PaymentOrder.Status.FAILED
                order.idempotency_key = f"{order.idempotency_key}_failed_{order.id}"
                order.save(update_fields=['status', 'idempotency_key'])
                
                bookings = order.bookings.all()
                seat_ids = [b.seat_id for b in bookings]
                bookings.update(status=Booking.Status.FAILED)
                Seat.objects.filter(id__in=seat_ids).update(is_booked=False)

    except PaymentOrder.DoesNotExist:
        return HttpResponseBadRequest("Order not found")

    return HttpResponse("Webhook processed successfully", status=200)


@login_required(login_url='/login/')
@csrf_exempt
def simulate_webhook(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Only POST method allowed")
        
    payment_id = request.POST.get('payment_id')
    status = request.POST.get('status') # 'success' or 'failure'
    
    if not payment_id or not status:
        return HttpResponseBadRequest("Missing payment_id or status")

    # Double check that the user owns the order before simulating
    order = get_object_or_404(PaymentOrder, payment_id=payment_id, user=request.user)
    
    # Construct simulated payload
    payload_data = {
        "payment_id": payment_id,
        "status": status,
        "simulated_at": timezone.now().isoformat()
    }
    payload_bytes = json.dumps(payload_data).encode('utf-8')
    
    # Compute signature
    mock_secret = settings.MOCK_WEBHOOK_SECRET.encode('utf-8')
    signature = hmac.new(mock_secret, payload_bytes, hashlib.sha256).hexdigest()
    
    # Inline-invoke webhook handler to bypass network & deadlock issues in single-threaded dev server
    factory = RequestFactory()
    mock_request = factory.post(
        '/movies/payment/webhook/',
        data=payload_bytes,
        content_type='application/json',
        HTTP_X_MOCK_SIGNATURE=signature
    )
    
    response = payment_webhook(mock_request)
    
    if response.status_code == 200:
        if status == 'success':
            messages.success(request, "Payment successful! Your tickets are booked.")
        else:
            messages.error(request, "Payment failed: The simulated card was declined.")
    else:
        messages.error(request, f"Webhook simulation failed with status {response.status_code}: {response.content.decode()}")
        
    return redirect('profile')
