from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class FolderScope(models.TextChoices):
    GENERAL = "GENERAL", "Allgemein"
    SENSITIVE = "SENSITIVE", "Sensibel"


class DocumentFolder(models.Model):
    name = models.CharField(max_length=150)
    scope = models.CharField(max_length=16, choices=FolderScope.choices)
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")

    class Meta:
        ordering = ["scope", "name"]
        unique_together = ("scope", "parent", "name")

    def __str__(self):
        return self.path_label

    @property
    def path_label(self):
        if self.parent:
            return f"{self.parent.path_label} / {self.name}"
        return self.name

    def level(self):
        depth = 0
        current = self.parent
        while current:
            depth += 1
            current = current.parent
        return depth


class DocumentQuerySet(models.QuerySet):
    def general(self):
        return self.filter(visibility=FolderScope.GENERAL)

    def sensitive(self):
        return self.filter(visibility=FolderScope.SENSITIVE)


class Document(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    folder = models.ForeignKey(
        DocumentFolder,
        on_delete=models.PROTECT,
        related_name="documents",
        null=True,
        blank=True,
    )
    visibility = models.CharField(max_length=16, choices=FolderScope.choices)
    file = models.FileField(upload_to="protected/")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_documents")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    objects = DocumentQuerySet.as_manager()

    class Meta:
        ordering = ["folder__name", "title"]

    def __str__(self):
        return self.title

    @property
    def file_name(self):
        return self.file.name.rsplit("/", 1)[-1]

    @property
    def file_extension(self):
        parts = self.file_name.rsplit(".", 1)
        if len(parts) == 2:
            return parts[1].lower()
        return ""

    @property
    def is_pdf(self):
        return self.file_extension == "pdf"

    @property
    def file_icon(self):
        extension = self.file_extension
        if extension == "pdf":
            return "pdf"
        if extension in {"doc", "docx"}:
            return "word"
        if extension == "svg":
            return "svg"
        if extension in {"png", "jpg", "jpeg"}:
            return "image"
        if extension in {"xls", "xlsx"}:
            return "sheet"
        if extension in {"ppt", "pptx"}:
            return "slides"
        if extension == "txt":
            return "text"
        return "file"

    def clean(self):
        if self.folder_id and self.visibility and self.folder.scope != self.visibility:
            raise ValidationError({"folder": "Der Ordner muss zum gewählten Dokumentbereich passen."})
