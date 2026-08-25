from django.urls import path

from .views import (
    AdminPasswordResetView,
    MemorialEntryCreateView,
    MemorialEntryUpdateView,
    MemorialPageView,
    MemberCsvImportView,
    MemberDirectoryView,
    ProfileDetailView,
    ProfileListView,
    ProfileUpdateView,
    UserCreateView,
    memorial_entry_delete_view,
    profile_photo_view,
)


urlpatterns = [
    path("mitglieder/", MemberDirectoryView.as_view(), name="member-directory"),
    path("totentafel/", MemorialPageView.as_view(), name="memorial-page"),
    path("totentafel/neu/", MemorialEntryCreateView.as_view(), name="memorial-create"),
    path("totentafel/<int:pk>/bearbeiten/", MemorialEntryUpdateView.as_view(), name="memorial-edit"),
    path("totentafel/<int:pk>/loeschen/", memorial_entry_delete_view, name="memorial-delete"),
    path("profiles/", ProfileListView.as_view(), name="profile-list"),
    path("profiles/neu/", UserCreateView.as_view(), name="user-create"),
    path("profiles/import/", MemberCsvImportView.as_view(), name="member-import"),
    path("profiles/<int:pk>/", ProfileDetailView.as_view(), name="profile-detail"),
    path("profiles/<int:pk>/bearbeiten/", ProfileUpdateView.as_view(), name="profile-edit"),
    path("profiles/<int:pk>/passwort/", AdminPasswordResetView.as_view(), name="profile-password-reset"),
    path("profiles/<int:pk>/foto/", profile_photo_view, name="profile-photo"),
]
