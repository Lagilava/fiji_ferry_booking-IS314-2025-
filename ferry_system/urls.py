from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from bookings import views as booking_views
from bookings.admin import admin_site, CustomAdminSite
from django.contrib.admin.views.decorators import staff_member_required

custom_admin = CustomAdminSite(name='custom_admin')

print("Admin site URLs:", [str(pattern) for pattern in admin_site.get_urls()])

urlpatterns = [
    path('admin/analytics-data/', staff_member_required(custom_admin.analytics_data_view), name='analytics-data'),
    path('admin/', admin_site.urls),
    path('accounts/', include('accounts.urls')),
    path('bookings/', include('bookings.urls')),
    path('', booking_views.homepage, name='home'),
    path('privacy_policy/', booking_views.privacy_policy, name='privacy_policy'),
    path('terms_of_service/', booking_views.terms_of_service, name='terms_of_service'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)