from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from bookings import views as booking_views

urlpatterns = [

    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('bookings/', include('bookings.urls')),
    path('', booking_views.homepage, name='home'),
    path('privacy_policy/', booking_views.privacy_policy, name='privacy_policy'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
