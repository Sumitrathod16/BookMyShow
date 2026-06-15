from django.urls import path
from . import views
from . import admin_views

urlpatterns=[
    path('',views.movie_list,name='movie_list'),
    path('<int:movie_id>/theaters',views.theater_list,name='theater_list'),
    path('theater/<int:theater_id>/seats/book/',views.book_seats,name='book_seats'),
    path('checkout/<str:payment_id>/', views.checkout, name='checkout'),
    path('payment/webhook/', views.payment_webhook, name='payment_webhook'),
    path('payment/cancel/<str:payment_id>/', views.payment_cancel, name='payment_cancel'),
    path('payment/simulate-webhook/', views.simulate_webhook, name='simulate_webhook'),
    path('admin/analytics/', admin_views.admin_analytics_dashboard, name='admin_analytics'),
    path('admin/analytics/api/', admin_views.admin_analytics_api, name='admin_analytics_api'),
]