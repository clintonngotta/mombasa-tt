from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["email", "display_name", "email_verified_at", "is_active", "is_staff", "date_joined"]
    search_fields = ["email", "display_name"]
    readonly_fields = ["id", "password", "last_login", "date_joined"]
