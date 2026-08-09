from django.contrib import admin

from .models import Document, DocumentFolder


@admin.register(DocumentFolder)
class DocumentFolderAdmin(admin.ModelAdmin):
    list_display = ("name", "scope", "parent")
    list_filter = ("scope",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "visibility", "folder", "uploaded_by", "uploaded_at")
    list_filter = ("visibility",)
