from django.contrib import admin

from .models import Organization

# Memberships and join requests are deliberately not editable here: platform operator authority is
# separate from club roles (REQ-004), and role changes need the audited flows from TASK-013.


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "town", "kind", "created_at"]
    search_fields = ["name", "town"]
