from django.urls import path

from . import minutes, views

organization_urlpatterns = [
    path("region-clubs/", views.RegionClubsView.as_view(), name="organization-region-clubs"),
    path("agenda/", views.AgendaView.as_view(), name="organization-agenda"),
    path("agenda/<uuid:pk>/", views.AgendaItemView.as_view(), name="organization-agenda-item"),
    path("articles/", views.ArticlesView.as_view(), name="organization-articles"),
    path("articles/<uuid:pk>/", views.ArticleView.as_view(), name="organization-article"),
    path(
        "articles/<uuid:pk>/publish/", views.PublishArticleView.as_view(), name="organization-article-publish"
    ),
    path("meetings/", views.MeetingsView.as_view(), name="organization-meetings"),
    path("meetings/<uuid:pk>/", views.MeetingView.as_view(), name="organization-meeting"),
    path(
        "meetings/<uuid:pk>/publish/", views.PublishMeetingView.as_view(), name="organization-meeting-publish"
    ),
    path("meetings/<uuid:pk>/cancel/", views.CancelMeetingView.as_view(), name="organization-meeting-cancel"),
    path("meetings/<uuid:pk>/minutes/", minutes.MinutesView.as_view(), name="organization-meeting-minutes"),
    path(
        "meetings/<uuid:pk>/minutes/approve/",
        minutes.ApproveMinutesView.as_view(),
        name="organization-meeting-minutes-approve",
    ),
    path(
        "meetings/<uuid:pk>/minutes/amendments/",
        minutes.AmendMinutesView.as_view(),
        name="organization-meeting-minutes-amendments",
    ),
    path(
        "meetings/<uuid:pk>/action-items/<uuid:action_pk>/",
        minutes.ActionItemView.as_view(),
        name="organization-meeting-action-item",
    ),
    path(
        "meetings/<uuid:pk>/documents/",
        minutes.MeetingDocumentsView.as_view(),
        name="organization-meeting-documents",
    ),
    path(
        "meetings/<uuid:pk>/documents/<uuid:document_pk>/",
        minutes.MeetingDocumentView.as_view(),
        name="organization-meeting-document",
    ),
    path("meetings/<uuid:pk>/answer/", views.AnswerMeetingView.as_view(), name="organization-meeting-answer"),
    path(
        "meetings/<uuid:pk>/attendance/",
        views.AttendanceView.as_view(),
        name="organization-meeting-attendance",
    ),
    path(
        "meetings/<uuid:pk>/penalties/",
        views.IssuePenaltiesView.as_view(),
        name="organization-meeting-penalties",
    ),
    path(
        "meetings/<uuid:pk>/penalties/<uuid:penalty_pk>/",
        views.PenaltyView.as_view(),
        name="organization-meeting-penalty",
    ),
    path(
        "meetings/<uuid:pk>/check-in/",
        views.CheckInMeetingView.as_view(),
        name="organization-meeting-check-in",
    ),
    path("sponsorships/", views.SponsorshipsView.as_view(), name="organization-sponsorships"),
    path(
        "sponsorships/<uuid:pk>/withdraw/",
        views.WithdrawSponsorshipView.as_view(),
        name="organization-sponsorship-withdraw",
    ),
]

tournament_urlpatterns = [
    path(
        "<uuid:tournament_pk>/sponsors/", views.TournamentSponsorsView.as_view(), name="tournament-sponsors"
    ),
    path(
        "<uuid:tournament_pk>/sponsorships/",
        views.TournamentSponsorshipsView.as_view(),
        name="tournament-sponsorships",
    ),
    *[
        path(
            f"<uuid:tournament_pk>/sponsorships/<uuid:pk>/{action}/",
            views.DecideSponsorshipView.as_view(action=action),
            name=f"tournament-sponsorship-{action}",
        )
        for action in ("accept", "decline")
    ],
]

me_urlpatterns = [
    path("agenda/", views.MyAgendaView.as_view(), name="my-agenda"),
    path("articles/", views.MyArticlesView.as_view(), name="my-articles"),
    path("meetings/", views.MyMeetingsView.as_view(), name="my-meetings"),
    path("action-items/", minutes.MyActionItemsView.as_view(), name="my-action-items"),
]

body_urlpatterns = [
    path("", views.RegionalBodiesView.as_view(), name="regional-bodies"),
]
