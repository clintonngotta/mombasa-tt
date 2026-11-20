from django.urls import path

from . import views

urlpatterns = [
    path("<uuid:pk>/url/", views.AttachmentLinkView.as_view(), name="attachment-link"),
    path("<uuid:pk>/content/", views.AttachmentContentView.as_view(), name="attachment-content"),
]
