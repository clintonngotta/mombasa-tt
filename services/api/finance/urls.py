from django.urls import path

from . import external, report_views, views

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
    path(
        "finance/campaigns/<uuid:pk>/dues/",
        views.CampaignDuesView.as_view(),
        name="organization-campaign-dues",
    ),
    path(
        "finance/campaigns/<uuid:pk>/remind/",
        views.RemindCampaignView.as_view(),
        name="organization-campaign-remind",
    ),
    path("finance/expenses/", views.ExpensesView.as_view(), name="organization-expenses"),
    path(
        "finance/expenses/<uuid:pk>/reverse/",
        views.ReverseExpenseView.as_view(),
        name="organization-expense-reverse",
    ),
    path(
        "finance/expenses/<uuid:pk>/receipt/",
        views.ExpenseReceiptView.as_view(),
        name="organization-expense-receipt",
    ),
    path("finance/summary/", views.SummaryView.as_view(), name="organization-finance-summary"),
    path(
        "finance/settings/", report_views.FinanceSettingsView.as_view(), name="organization-finance-settings"
    ),
    path(
        "finance/external-sources/",
        external.ExternalSourcesView.as_view(),
        name="organization-external-sources",
    ),
    path(
        "finance/external-sources/<uuid:pk>/",
        external.ExternalSourceView.as_view(),
        name="organization-external-source",
    ),
    path(
        "finance/external-income/", external.ExternalIncomeView.as_view(), name="organization-external-income"
    ),
    path(
        "finance/external-income/<uuid:pk>/reverse/",
        external.ReverseExternalIncomeView.as_view(),
        name="organization-external-income-reverse",
    ),
    path("finance/income-totals/", external.IncomeTotalsView.as_view(), name="organization-income-totals"),
    path("annual-reports/", report_views.AnnualReportsView.as_view(), name="organization-annual-reports"),
    path(
        "annual-reports/<uuid:pk>/",
        report_views.AnnualReportView.as_view(),
        name="organization-annual-report",
    ),
    path(
        "annual-reports/<uuid:pk>/publish/",
        report_views.PublishReportView.as_view(),
        name="organization-annual-report-publish",
    ),
    path(
        "annual-reports/<uuid:pk>/amend/",
        report_views.AmendReportView.as_view(),
        name="organization-annual-report-amend",
    ),
    path(
        "annual-reports/<uuid:pk>/export.csv",
        report_views.ExportReportView.as_view(kind="csv"),
        name="organization-annual-report-csv",
    ),
    path(
        "annual-reports/<uuid:pk>/export.pdf",
        report_views.ExportReportView.as_view(kind="pdf"),
        name="organization-annual-report-pdf",
    ),
    path("finance-purposes/", views.PurposesView.as_view(), name="organization-finance-purposes"),
    path("welfare-projects/", views.WelfareProjectsView.as_view(), name="organization-welfare-projects"),
    path(
        "welfare-projects/<uuid:pk>/", views.WelfareProjectView.as_view(), name="organization-welfare-project"
    ),
    path(
        "welfare-projects/<uuid:pk>/hide/",
        views.HideWelfareView.as_view(),
        name="organization-welfare-project-hide",
    ),
    path(
        "welfare-projects/<uuid:pk>/close/",
        views.CloseWelfareView.as_view(),
        name="organization-welfare-project-close",
    ),
    path(
        "welfare-projects/<uuid:pk>/due/",
        views.WelfareDueView.as_view(),
        name="organization-welfare-project-due",
    ),
    path(
        "welfare-projects/<uuid:pk>/contributions/",
        views.WelfareContributionsView.as_view(),
        name="organization-welfare-contributions",
    ),
    path(
        "welfare-projects/<uuid:pk>/contributions/<uuid:contribution_pk>/reverse/",
        views.ReverseWelfareContributionView.as_view(),
        name="organization-welfare-contribution-reverse",
    ),
    path(
        "welfare-projects/<uuid:pk>/expenses/",
        views.WelfareExpensesView.as_view(),
        name="organization-welfare-expenses",
    ),
    path("finance/balances/", views.BalancesView.as_view(), name="organization-balances"),
    path("my-finances/", views.MyFinancesView.as_view(), name="organization-my-finances"),
]
