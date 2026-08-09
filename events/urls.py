from django.urls import path

from .views import EventCreateView, EventDeleteView, EventListView, EventUpdateView


urlpatterns = [
    path("", EventListView.as_view(), name="event-list"),
    path("neu/", EventCreateView.as_view(), name="event-create"),
    path("<int:pk>/bearbeiten/", EventUpdateView.as_view(), name="event-edit"),
    path("<int:pk>/loeschen/", EventDeleteView.as_view(), name="event-delete"),
]
