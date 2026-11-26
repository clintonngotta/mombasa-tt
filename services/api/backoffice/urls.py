from django.urls import path

from . import views

urlpatterns = [
    path("overview/", views.OverviewView.as_view(), name="platform-overview"),
    path("accounts/", views.AccountsView.as_view(), name="platform-accounts"),
    path("accounts/<uuid:pk>/", views.AccountView.as_view(), name="platform-account"),
    path("organizations/", views.OrganizationsView.as_view(), name="platform-organizations"),
    path("countries/<str:code>/", views.CountryView.as_view(), name="platform-country"),
    path("countries/<str:code>/regions/", views.RegionsView.as_view(), name="platform-regions"),
    path("regions/<int:pk>/", views.RegionView.as_view(), name="platform-region"),
    path("regions/<int:pk>/cities/", views.CitiesView.as_view(), name="platform-cities"),
    path("cities/<int:pk>/", views.CityView.as_view(), name="platform-city"),
]
