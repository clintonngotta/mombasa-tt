from django.urls import path

from . import views

# Mounted under /organizations/<organization_pk>/.
urlpatterns = [
    path("finance/charges/", views.ChargesView.as_view(), name="organization-charges"),
    path(
        "finance/charges/<uuid:pk>/waive/", views.WaiveChargeView.as_view(), name="organization-charge-waive"
    ),
    path("finance/payments/", views.PaymentsView.as_view(), name="organization-payments"),
    path(
        "finance/payments/<uuid:pk>/allocate/",
        views.AllocateView.as_view(),
        name="organization-payment-allocate",
    ),
    path(
        "finance/payments/<uuid:pk>/reverse/",
        views.ReversePaymentView.as_view(),
        name="organization-payment-reverse",
    ),
    path("finance/campaigns/", views.CampaignsView.as_view(), name="organization-campaigns"),
    path("finance/campaigns/<uuid:pk>/", views.CampaignView.as_view(), name="organization-campaign"),
    path(
        "finance/campaigns/<uuid:pk>/close/",
        views.CloseCampaignView.as_view(),
        name="organization-campaign-close",
    ),
    path(
        "finance/campaigns/<uuid:pk>/terms/",
        views.CampaignTermView.as_view(),
        name="organization-campaign-terms",
    ),
    path("finance/balances/", views.BalancesView.as_view(), name="organization-balances"),
    path("my-finances/", views.MyFinancesView.as_view(), name="organization-my-finances"),
]
