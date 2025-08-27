from django.urls import path
from django.views.generic import TemplateView
from bookings import views

app_name = 'bookings'

urlpatterns = [
    path('', views.homepage, name='home'),
    path('history/', views.booking_history, name='booking_history'),
    path('ticket/<int:booking_id>/', views.view_tickets, name='view_tickets'),
    path('generate_ticket/<int:booking_id>/', views.generate_ticket, name='generate_ticket'),
    path('view_cargo/<str:qr_data>/', views.view_cargo, name='view_cargo'),
    path('view_ticket/<str:qr_token>/', views.view_ticket, name='view_ticket'),
    path('book/', views.book_ticket, name='book'),
    path('process_payment/<int:booking_id>/', views.process_payment, name='process_payment'),
    path('success/', views.payment_success, name='success'),
    path('cancel/', views.payment_cancel, name='cancel'),
    path('modify/<int:booking_id>/', views.modify_booking, name='modify_booking'),
    path('cancel_booking/<int:booking_id>/', views.cancel_booking, name='cancel_booking'),
    path('get_schedule_updates/', views.get_schedule_updates, name='get_schedule_updates'),
    path('get_pricing/', views.get_pricing, name='get_pricing'),
    path('stripe_webhook/', views.stripe_webhook, name='stripe_webhook'),
    path('weather/stream/', views.weather_stream, name='weather_stream'),
    path('validate_file/', views.validate_file, name='validate_file'),
    path('validate-step/', views.validate_step, name='validate_step'),
    path('privacy-policy/', TemplateView.as_view(template_name='privacy_policy.html'), name='privacy_policy'),
]