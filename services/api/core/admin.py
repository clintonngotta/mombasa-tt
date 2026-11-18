from django.contrib import admin
from django.db import transaction

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
        from organizations.models import OfficialAppointment, Organization
        from profiles.models import PlayerProfile

        previous = Region.objects.get(pk=obj.pk) if change else None
        super().save_model(request, obj, form, change)
        if previous and (previous.name != obj.name or previous.country_id != obj.country_id):
            for model in (PlayerProfile, Organization):
                model.objects.filter(country=previous.country_id, region__iexact=previous.name).update(
                    country=obj.country_id, region=obj.name
                )
            OfficialAppointment.objects.filter(region=obj).update(country=obj.country)


@admin.register(City)
class CityAdmin(PlatformOnlyAdmin):
    list_display = ("name", "region")
    list_filter = ("region__country",)
    search_fields = ("name", "region__name")

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        from organizations.models import Organization
        from profiles.models import PlayerProfile

        previous = City.objects.select_related("region").get(pk=obj.pk) if change else None
        super().save_model(request, obj, form, change)
        if previous and (previous.name != obj.name or previous.region_id != obj.region_id):
            before = {"country": previous.region.country_id, "region__iexact": previous.region.name}
            after = {"country": obj.region.country_id, "region": obj.region.name}
            PlayerProfile.objects.filter(**before, city__iexact=previous.name).update(**after, city=obj.name)
            Organization.objects.filter(**before, town__iexact=previous.name).update(**after, town=obj.name)
