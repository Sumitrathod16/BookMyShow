from datetime import timedelta
from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.utils import timezone
from django.core.cache import cache
from django.db.models import Sum, Count, Q, ExpressionWrapper, FloatField
from django.db.models.functions import Cast, ExtractHour

from .models import Booking, Theater, PaymentOrder


@staff_member_required(login_url='/login/')
def admin_analytics_dashboard(request):
    """
    Renders the admin analytics dashboard HTML page.
    Role-based authentication is enforced via @staff_member_required.
    """
    return render(request, 'movies/admin_analytics.html')


@staff_member_required(login_url='/login/')
def admin_analytics_api(request):
    """
    API endpoint returning optimized JSON analytics data.
    Implements a 60-second caching strategy to prevent database load.
    Supports ?refresh=true to bypass cache and force reload from the database.
    """
    cache_key = 'admin_analytics_dashboard_data'
    force_refresh = request.GET.get('refresh') == 'true'
    data = None if force_refresh else cache.get(cache_key)
    
    if data is None:
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        weekly_start = now - timedelta(days=7)
        monthly_start = now - timedelta(days=30)
        
        # 1. Total Revenue Aggregations (Daily, Weekly, Monthly) - Optimized to a single query
        revenue_stats = PaymentOrder.objects.filter(
            status=PaymentOrder.Status.COMPLETED,
            created_at__gte=monthly_start
        ).aggregate(
            daily=Sum('amount', filter=Q(created_at__gte=today_start)),
            weekly=Sum('amount', filter=Q(created_at__gte=weekly_start)),
            monthly=Sum('amount')
        )
        
        daily_rev = revenue_stats['daily'] or 0.0
        weekly_rev = revenue_stats['weekly'] or 0.0
        monthly_rev = revenue_stats['monthly'] or 0.0

        # 2. Most Popular Movies (top 10 based on confirmed bookings)
        popular_movies = list(
            Booking.objects.filter(status=Booking.Status.CONFIRMED)
            .values('movie__name')
            .annotate(booking_count=Count('id'))
            .order_by('-booking_count')[:10]
        )

        # 3. Busiest Theaters (top 10 based on seat occupancy rate)
        # Busiest theaters: (booked seats / total seats) * 100
        busiest_theaters = list(
            Theater.objects.annotate(
                total_seats=Count('seats'),
                booked_seats=Count('seats', filter=Q(seats__is_booked=True))
            )
            .filter(total_seats__gt=0)
            .annotate(
                occupancy_rate=ExpressionWrapper(
                    Cast('booked_seats', FloatField()) / Cast('total_seats', FloatField()) * 100,
                    output_field=FloatField()
                )
            )
            .order_by('-occupancy_rate')[:10]
            .values('name', 'total_seats', 'booked_seats', 'occupancy_rate')
        )

        # 4. Peak Booking Hours (confirmed bookings grouped by hour 0-23)
        peak_hours = list(
            Booking.objects.filter(status=Booking.Status.CONFIRMED)
            .annotate(hour=ExtractHour('booked_at'))
            .values('hour')
            .annotate(count=Count('id'))
            .order_by('hour')
        )

        # 5. Cancellation Rates & Order Statuses
        order_stats = PaymentOrder.objects.aggregate(
            total=Count('id'),
            completed=Count('id', filter=Q(status=PaymentOrder.Status.COMPLETED)),
            cancelled=Count('id', filter=Q(status=PaymentOrder.Status.CANCELLED)),
            failed=Count('id', filter=Q(status=PaymentOrder.Status.FAILED)),
            expired=Count('id', filter=Q(status=PaymentOrder.Status.EXPIRED))
        )
        
        total_orders = order_stats['total'] or 0
        cancellation_rate = 0.0
        if total_orders > 0:
            cancellation_rate = (
                (order_stats['cancelled'] + order_stats['failed'] + order_stats['expired'])
                / total_orders * 100
            )

        data = {
            'revenue': {
                'daily': float(daily_rev),
                'weekly': float(weekly_rev),
                'monthly': float(monthly_rev),
            },
            'popular_movies': popular_movies,
            'busiest_theaters': busiest_theaters,
            'peak_hours': peak_hours,
            'order_stats': {
                'total': total_orders,
                'completed': order_stats['completed'],
                'cancelled': order_stats['cancelled'],
                'failed': order_stats['failed'],
                'expired': order_stats['expired'],
                'cancellation_rate': round(cancellation_rate, 2)
            },
            'cache_time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'source': 'Database Query'
        }
        
        # Cache the resulting analytics data for 60 seconds
        cache.set(cache_key, data, timeout=60)
    else:
        # Mark source as cache
        data['source'] = 'Cache'

    return JsonResponse(data)
