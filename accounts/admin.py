import secrets
import string
from django.contrib import admin, messages
from django.contrib.auth.forms import AdminPasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.core.mail import send_mail
from django.shortcuts import render, redirect, get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone
from django.db import transaction
from django.http import HttpResponseRedirect

from bookings.admin import admin_site
from bookings.models import Booking
from .models import User


# ──────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────

def _generate_temp_password(length=14):
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _clear_user_sessions(user):
    """Delete all DB sessions that belong to this user."""
    from django.contrib.sessions.models import Session
    from django.conf import settings
    cleared = 0
    uid = str(user.pk)
    for session in Session.objects.all():
        try:
            data = session.get_decoded()
            if data.get('_auth_user_id') == uid:
                session.delete()
                cleared += 1
        except Exception:
            pass
    return cleared


# ──────────────────────────────────────────────────────────────────
#  Inline: recent bookings on the user change page
# ──────────────────────────────────────────────────────────────────

class UserBookingInline(admin.TabularInline):
    model = Booking
    fk_name = 'user'
    extra = 0
    max_num = 0  # read-only — no adding
    can_delete = False
    fields = ('id', 'route_display', 'departure_display', 'status', 'total_price', 'booking_date')
    readonly_fields = fields
    ordering = ('-booking_date',)
    show_change_link = True
    verbose_name = 'Booking'
    verbose_name_plural = 'Bookings'

    def route_display(self, obj):
        try:
            r = obj.schedule.route
            return f"{r.departure_port.name} → {r.destination_port.name}"
        except Exception:
            return '—'
    route_display.short_description = 'Route'

    def departure_display(self, obj):
        try:
            return obj.schedule.departure_time.strftime('%d %b %Y %H:%M')
        except Exception:
            return '—'
    departure_display.short_description = 'Departure'


# ──────────────────────────────────────────────────────────────────
#  UserAdmin
# ──────────────────────────────────────────────────────────────────

@admin.register(User, site=admin_site)
class UserAdmin(admin.ModelAdmin):

    # ── List view ──
    list_display = (
        'email', 'username', 'full_name_display', 'phone_number',
        'is_active_badge', 'is_staff', 'booking_count', 'last_login', 'created_at',
    )
    list_filter = ('is_active', 'is_staff', 'is_superuser')
    search_fields = ('email', 'username', 'first_name', 'last_name', 'phone_number')
    readonly_fields = ('created_at', 'updated_at', 'last_login', 'booking_count_display')
    list_per_page = 25
    ordering = ('-created_at',)
    list_display_links = ('email', 'username')
    actions = [
        'action_set_temp_password',
        'action_send_reset_email',
        'action_activate',
        'action_deactivate',
        'action_force_logout',
        'action_anonymise',
    ]
    inlines = [UserBookingInline]

    fieldsets = (
        ('Identity', {
            'fields': ('email', 'username', 'first_name', 'last_name', 'phone_number'),
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'classes': ('collapse',),
        }),
        ('Stats', {
            'fields': ('last_login', 'created_at', 'updated_at', 'booking_count_display'),
            'classes': ('collapse',),
        }),
    )

    # ── Computed columns ──

    def full_name_display(self, obj):
        name = f"{obj.first_name} {obj.last_name}".strip()
        return name or '—'
    full_name_display.short_description = 'Name'

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color:#059669;font-weight:700;">✓ Active</span>')
        return format_html('<span style="color:#dc2626;font-weight:700;">✗ Inactive</span>')
    is_active_badge.short_description = 'Status'
    is_active_badge.admin_order_field = 'is_active'

    def booking_count(self, obj):

        count = Booking.objects.filter(user=obj).count()
        if count:
            url = reverse('custom_admin:bookings_booking_changelist') + f'?user__id__exact={obj.pk}'
            return format_html('<a href="{}">{} booking{}</a>', url, count, 's' if count != 1 else '')
        return '0'
    booking_count.short_description = 'Bookings'

    def booking_count_display(self, obj):

        return Booking.objects.filter(user=obj).count()
    booking_count_display.short_description = 'Total bookings'

    # ── Change view: inject password-set form ──

    def change_view(self, request, object_id, form_url='', extra_context=None):
        user = get_object_or_404(User, pk=object_id)
        extra_context = extra_context or {}

        if request.method == 'POST' and '_set_password' in request.POST:
            pw_form = AdminPasswordChangeForm(user, request.POST)
            if pw_form.is_valid():
                pw_form.save()
                messages.success(request, f"Password for {user.email} has been updated.")
                # Invalidate their sessions so old password doesn't work
                cleared = _clear_user_sessions(user)
                if cleared:
                    messages.info(request, f"{cleared} active session(s) were logged out.")
                return HttpResponseRedirect(request.path)
            extra_context['pw_form'] = pw_form
        else:
            extra_context['pw_form'] = AdminPasswordChangeForm(user)

        extra_context['user_obj'] = user
        return super().change_view(request, object_id, form_url, extra_context)

    # ── Actions ──

    @admin.action(description='🔑 Set a temporary password (shown once)')
    def action_set_temp_password(self, request, queryset):
        results = []
        for user in queryset:
            pwd = _generate_temp_password()
            user.set_password(pwd)
            user.save(update_fields=['password'])
            _clear_user_sessions(user)
            results.append(f"{user.email}: <strong>{pwd}</strong>")
        msg = "Temporary passwords set (save these — they won't be shown again):<br>" + "<br>".join(results)
        self.message_user(request, format_html(msg), level=messages.WARNING)

    @admin.action(description='📧 Send password reset email')
    def action_send_reset_email(self, request, queryset):
        from django.contrib.auth.forms import PasswordResetForm
        sent, skipped = 0, 0
        for user in queryset:
            if not user.email:
                skipped += 1
                continue
            form = PasswordResetForm({'email': user.email})
            if form.is_valid():
                form.save(
                    request=request,
                    use_https=request.is_secure(),
                    email_template_name='accounts/password_reset_email.txt',
                    html_email_template_name='accounts/password_reset_email.html',
                    subject_template_name='accounts/password_reset_subject.txt',
                )
                sent += 1
            else:
                skipped += 1
        self.message_user(request, f"Reset email sent to {sent} user(s). {skipped} skipped (no email).")

    @admin.action(description='✅ Activate selected accounts')
    def action_activate(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} account(s) activated.")

    @admin.action(description='🚫 Deactivate selected accounts')
    def action_deactivate(self, request, queryset):
        updated = queryset.filter(is_superuser=False).update(is_active=False)
        self.message_user(request, f"{updated} account(s) deactivated (superusers protected).")

    @admin.action(description='🔓 Force logout (clear all sessions)')
    def action_force_logout(self, request, queryset):
        total = 0
        for user in queryset:
            total += _clear_user_sessions(user)
        self.message_user(request, f"{total} session(s) terminated across {queryset.count()} account(s).")

    @admin.action(description='🗑️ Anonymise account (GDPR / deletion request)')
    def action_anonymise(self, request, queryset):
        if queryset.filter(is_superuser=True).exists():
            self.message_user(request, "Cannot anonymise superuser accounts.", level=messages.ERROR)
            return
        count = 0
        for user in queryset:
            uid = user.pk
            user.email = f"deleted_{uid}@anonymised.local"
            user.username = f"deleted_{uid}"
            user.first_name = ''
            user.last_name = ''
            user.phone_number = ''
            user.is_active = False
            user.set_unusable_password()
            user.save()
            _clear_user_sessions(user)
            count += 1
        self.message_user(request, f"{count} account(s) anonymised and deactivated.")

    # ── Custom URLs: user support dashboard + transfer bookings ──

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('support/', self.admin_site.admin_view(self.support_view), name='accounts_user_support'),
            path('<int:user_id>/transfer-bookings/', self.admin_site.admin_view(self.transfer_bookings_view), name='accounts_user_transfer'),
            path('<int:user_id>/claim-guest/', self.admin_site.admin_view(self.claim_guest_view), name='accounts_user_claim_guest'),
        ]
        return custom + urls

    def support_view(self, request):
        """User support dashboard: surfaced problem accounts."""

        threshold_inactive = timezone.now() - timezone.timedelta(days=90)

        never_logged_in = User.objects.filter(last_login__isnull=True, is_active=True).order_by('-created_at')[:20]
        long_inactive = User.objects.filter(
            last_login__lt=threshold_inactive, is_active=True
        ).order_by('last_login')[:20]
        deactivated = User.objects.filter(is_active=False).order_by('-updated_at')[:20]
        has_pending = User.objects.filter(
            booking__status='pending'
        ).distinct().order_by('-created_at')[:20]

        # Guest bookings that share an email with a registered account
        from django.db.models import Subquery, OuterRef
        registered_emails = User.objects.values('email')
        claimable_guest_bookings = Booking.objects.filter(
            user__isnull=True,
            guest_email__isnull=False,
            guest_email__in=registered_emails,
        ).select_related('schedule__route__departure_port', 'schedule__route__destination_port')[:20]

        context = {
            **self.admin_site.each_context(request),
            'title': 'User Support Dashboard',
            'never_logged_in': never_logged_in,
            'long_inactive': long_inactive,
            'deactivated': deactivated,
            'has_pending': has_pending,
            'claimable_guest_bookings': claimable_guest_bookings,
            'opts': self.model._meta,
        }
        return TemplateResponse(request, 'admin/accounts/user_support.html', context)

    def transfer_bookings_view(self, request, user_id):
        """Transfer all bookings from one user to another."""

        source = get_object_or_404(User, pk=user_id)

        if request.method == 'POST':
            target_email = request.POST.get('target_email', '').strip()
            try:
                target = User.objects.get(email=target_email)
            except User.DoesNotExist:
                messages.error(request, f"No user found with email: {target_email}")
            else:
                if target.pk == source.pk:
                    messages.error(request, "Source and target are the same account.")
                else:
                    with transaction.atomic():
                        count = Booking.objects.filter(user=source).update(user=target)
                    messages.success(request, f"{count} booking(s) transferred from {source.email} to {target.email}.")
                    return redirect(reverse('custom_admin:accounts_user_change', args=[source.pk]))

        bookings = Booking.objects.filter(user=source).select_related(
            'schedule__route__departure_port', 'schedule__route__destination_port'
        ).order_by('-booking_date')
        context = {
            **self.admin_site.each_context(request),
            'title': f'Transfer bookings — {source.email}',
            'source': source,
            'bookings': bookings,
            'opts': self.model._meta,
        }
        return TemplateResponse(request, 'admin/accounts/transfer_bookings.html', context)

    def claim_guest_view(self, request, user_id):
        """Link guest bookings (by email) to a registered user account."""

        user = get_object_or_404(User, pk=user_id)
        guest_bookings = Booking.objects.filter(
            user__isnull=True, guest_email__iexact=user.email
        ).select_related('schedule__route__departure_port', 'schedule__route__destination_port')

        if request.method == 'POST':
            booking_ids = request.POST.getlist('booking_ids')
            if booking_ids:
                with transaction.atomic():
                    count = Booking.objects.filter(
                        pk__in=booking_ids, user__isnull=True
                    ).update(user=user, guest_email=None)
                messages.success(request, f"{count} guest booking(s) claimed for {user.email}.")
            else:
                messages.warning(request, "No bookings selected.")
            return redirect(reverse('custom_admin:accounts_user_change', args=[user.pk]))

        context = {
            **self.admin_site.each_context(request),
            'title': f'Claim guest bookings — {user.email}',
            'user_obj': user,
            'guest_bookings': guest_bookings,
            'opts': self.model._meta,
        }
        return TemplateResponse(request, 'admin/accounts/claim_guest.html', context)
