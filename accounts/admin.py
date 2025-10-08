from django.contrib import admin
from bookings.admin import admin_site
from .models import User

@admin.register(User, site=admin_site)
class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'username', 'first_name', 'last_name', 'is_active', 'is_staff', 'created_at', 'updated_at')
    list_filter = ('is_active', 'is_staff')
    search_fields = ('email', 'username', 'first_name', 'last_name')
    readonly_fields = ('created_at', 'updated_at')
    list_per_page = 25
    ordering = ('email',)
    icon_name = 'user'
    list_display_links = ('email', 'username')
    fieldsets = (
        ('General Info', {'fields': ('email', 'username', 'first_name', 'last_name')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )