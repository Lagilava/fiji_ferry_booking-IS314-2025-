from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from bookings import views as bookings_views 

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('bookings/', include('bookings.urls')),
    path('', bookings_views.homepage, name='home'),
    path('api/schedules/', bookings_views.get_schedule_updates, name='get_schedule_updates'),
    path('privacy-policy/', bookings_views.privacy_policy, name='privacy_policy'),
    path('api/weather/', bookings_views.get_weather_conditions, name='get_weather_conditions'),
    path('weather/stream/', bookings_views.weather_stream, name='weather_stream'),
    path('validate-step/', bookings_views.validate_step, name='validate_step'),
    path('bookings/create-checkout-session/', bookings_views.create_checkout_session, name='create_checkout_session'),
    path('bookings/get-pricing/', bookings_views.get_pricing, name='get-pricing'),

]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
