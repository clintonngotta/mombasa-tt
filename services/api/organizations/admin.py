from django.contrib import admin

from core.admin import PlatformOnlyAdmin

from .models import OfficialAppointment, Organization


@admin.register(OfficialAppointment)
class OfficialAppointmentAdmin(PlatformOnlyAdmin):
    list_display = ("user", "country", "region")
    list_filter = ("country", "region")
    search_fields = ("user__display_name", "user__email")

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "town", "kind", "created_at"]
    search_fields = ["name", "town"]
