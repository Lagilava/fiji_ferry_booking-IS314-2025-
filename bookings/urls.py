from django.urls import path
from bookings import views

app_name = 'bookings'

urlpatterns = [
    path('', views.homepage, name='home'),  # Root URL for homepage
    path('homepage/', views.homepage, name='homepage'),  # Backward compatibility
    path('history/', views.booking_history, name='booking_history'),
    path('ticket/<int:booking_id>/', views.view_tickets, name='view_tickets'),
    path('generate_ticket/<int:booking_id>/', views.generate_ticket, name='generate_ticket'),
    path('view_cargo/<int:cargo_id>/', views.view_cargo, name='view_cargo'),  # Fixed: Changed qr_data to cargo_id
    path('view_ticket/<str:qr_token>/', views.view_ticket, name='view_ticket'),
    path('book/', views.book_ticket, name='book_ticket'),
    path('process_payment/<int:booking_id>/', views.process_payment, name='process_payment'),
    path('success/', views.payment_success, name='success'),
    path('cancel/', views.payment_cancel, name='cancel'),
    path('modify/<int:booking_id>/', views.modify_booking, name='modify_booking'),
    path('cancel_booking/<int:booking_id>/', views.cancel_booking, name='cancel_booking'),
    path('api/schedules/', views.get_schedule_updates, name='get_schedule_updates'),  # Fixed: Changed to api/schedules/
    path('get_pricing/', views.get_pricing, name='get-pricing'),  # Note: Consider moving to api/pricing/
    path('stripe_webhook/', views.stripe_webhook, name='stripe_webhook'),
    path('api/weather/stream/', views.weather_stream, name='weather_stream'),  # Consistent with /api/
    path('validate_file/', views.validate_file, name='validate_file'),
    path('validate_step/', views.validate_step, name='validate_step'),
    path('privacy_policy/', views.privacy_policy, name='privacy_policy'),
    path('api/routes/', views.routes_api, name='routes_api'),
    path('api/weather/', views.get_weather_conditions, name='get_weather_conditions'),  # Added
    path('create_checkout_session/', views.create_checkout_session, name='create_checkout_session'),
    path('check_session/', views.check_session, name='check_session'),
    path('booking/<int:booking_id>/pdf/', views.booking_pdf, name='booking_pdf'),
]