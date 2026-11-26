from django.contrib import admin
from django.db import transaction

from .geography import city_changed, region_changed
from .models import City, Country, Region
from .permissions import is_platform_super_admin


class PlatformOnlyAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return is_platform_super_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return is_platform_super_admin(request.user)

    def has_add_permission(self, request):
        return is_platform_super_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_platform_super_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_platform_super_admin(request.user)


@admin.register(Country)
class CountryAdmin(PlatformOnlyAdmin):
    list_display = ("code", "name", "catalogue_only")
    search_fields = ("code", "name")

    def get_readonly_fields(self, request, obj=None):
        return ("code",) if obj else ()


@admin.register(Region)
class RegionAdmin(PlatformOnlyAdmin):
    list_display = ("name", "country")
    list_filter = ("country",)
    search_fields = ("name", "country__name")

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        previous = Region.objects.get(pk=obj.pk) if change else None
        super().save_model(request, obj, form, change)
        if previous:
            region_changed(previous, obj)


@admin.register(City)
class CityAdmin(PlatformOnlyAdmin):
    list_display = ("name", "region")
    list_filter = ("region__country",)
    search_fields = ("name", "region__name")

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        previous = City.objects.select_related("region").get(pk=obj.pk) if change else None
        super().save_model(request, obj, form, change)
        if previous:
            city_changed(previous, obj)
