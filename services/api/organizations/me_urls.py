from django.urls import path

from . import views

urlpatterns = [
    path("memberships/", views.MyMembershipsView.as_view(), name="me-memberships"),
    path("join-requests/", views.MyJoinRequestsView.as_view(), name="me-join-requests"),
]
