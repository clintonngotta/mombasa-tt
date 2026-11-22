from django.contrib import admin

from core.admin import PlatformOnlyAdmin

from .models import OfficialAppointment, Organization


@admin.register(OfficialAppointment)
class OfficialAppointmentAdmin(PlatformOnlyAdmin):
    """Read-only history (decision D4): officials now hold `tournaments.approve` in their body."""

    list_display = ("user", "country", "region")
    list_filter = ("country", "region")
    search_fields = ("user__display_name", "user__email")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Organization)
class OrganizationAdmin(PlatformOnlyAdmin):
    """A club's country and region decide which officials govern it, so only the platform edits them here."""

    list_display = ["name", "town", "kind", "created_at"]
    search_fields = ["name", "town"]
