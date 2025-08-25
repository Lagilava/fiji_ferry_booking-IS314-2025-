from django.contrib import admin
from .models import User

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'username', 'first_name', 'last_name', 'is_active', 'is_staff', 'created_at', 'updated_at')
    search_fields = ('email', 'username')
    list_filter = ('is_active', 'is_staff')
    readonly_fields = ('created_at', 'updated_at')