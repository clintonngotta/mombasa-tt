from django.contrib import admin

from .models import JoinRequest, Membership, Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "town", "kind", "created_at"]
    search_fields = ["name", "town"]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["organization", "user", "role", "status", "joined_at"]
    list_filter = ["role", "status"]


@admin.register(JoinRequest)
class JoinRequestAdmin(admin.ModelAdmin):
    list_display = ["organization", "user", "status", "created_at", "decided_at"]
    list_filter = ["status"]
