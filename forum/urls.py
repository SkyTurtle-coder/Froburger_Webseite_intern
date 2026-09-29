from django.urls import path

from . import views

app_name = "forum"
urlpatterns = [
    path("", views.issue_list, name="list"),
    path("neu/", views.issue_edit, name="create"),
    path("<int:pk>/", views.issue_detail, name="detail"),
    path("<int:pk>/bearbeiten/", views.issue_edit, name="edit"),
    path("<int:pk>/loeschen/", views.issue_delete, name="delete"),
    path("<int:pk>/pdf/", views.issue_pdf, name="pdf"),
    path("<int:pk>/kommentieren/", views.comment_create, name="comment-create"),
    path("kommentar/<int:pk>/", views.comment_link, name="comment-link"),
    path("kommentar/<int:pk>/bearbeiten/", views.comment_edit, name="comment-edit"),
    path("kommentar/<int:pk>/loeschen/", views.comment_delete, name="comment-delete"),
    path("kommentar/<int:pk>/like/", views.comment_like, name="comment-like"),
]
