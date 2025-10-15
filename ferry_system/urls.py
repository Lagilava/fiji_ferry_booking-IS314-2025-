# main urls.py
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from bookings import views as booking_views
from bookings.admin import admin_site, CustomAdminSite

# Initialize custom admin site (all URLs are now handled internally)
custom_admin = CustomAdminSite(name='custom_admin')

urlpatterns = [
    # Admin URLs (now includes all enhanced endpoints)
    path('admin/', admin_site.urls),

    # User-facing URLs
    path('accounts/', include('accounts.urls')),
    path('bookings/', include('bookings.urls')),
    path('', booking_views.homepage, name='home'),
    path('privacy_policy/', booking_views.privacy_policy, name='privacy_policy'),
    path('terms_of_service/', booking_views.terms_of_service, name='terms_of_service'),
]

# Static files in debug mode
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

print("Admin site URLs configured with enhanced endpoints")