from django.urls import path

from .views import (
    document_delete_view,
    document_download_view,
    document_edit_view,
    document_hub,
    document_preview_view,
    document_scope_view,
)


urlpatterns = [
    path("datei/<int:pk>/bearbeiten/", document_edit_view, name="document-edit"),
    path("datei/<int:pk>/loeschen/", document_delete_view, name="document-delete"),
    path("datei/<int:pk>/ansehen/", document_preview_view, name="document-preview"),
    path("datei/<int:pk>/", document_download_view, name="document-download"),
    path("", document_hub, name="document-hub"),
    path("<slug:scope>/", document_scope_view, name="document-scope"),
]
