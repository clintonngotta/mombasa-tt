from django.contrib import admin

from core.admin import PlatformOnlyAdmin

from .models import User


@admin.register(User)
class UserAdmin(PlatformOnlyAdmin):
    """Only a platform super admin can grant platform authority or change accounts."""

    list_display = [
        "email",
        "phone",
        "display_name",
        "email_verified_at",
        "is_active",
        "is_staff",
        "date_joined",
    ]
    search_fields = ["email", "phone", "display_name"]
    readonly_fields = ["id", "password", "last_login", "date_joined"]
