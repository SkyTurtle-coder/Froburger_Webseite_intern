import re

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
    file = models.FileField(upload_to="protected/", max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_documents")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    spreadsheet_revision = models.PositiveIntegerField(default=0)

    objects = DocumentQuerySet.as_manager()

    class Meta:
        ordering = ["folder__name", "title"]

    def __str__(self):
        return self.title

    @property
    def file_name(self):
        """Return a stable user-facing name, never an internal storage name."""
        file_name = self.file.name.rsplit("/", 1)[-1]
        if self.pk:
            prefix = f"document-{self.pk}-"
            while file_name.startswith(prefix):
                file_name = file_name[len(prefix) :]

        stem, separator, extension = file_name.rpartition(".")
        if separator:
            cleaned_stem = re.sub(r"-Version-\d+$", "", stem)
            if cleaned_stem:
                file_name = f"{cleaned_stem}.{extension}"

        # Django's storage adds random suffixes when a physical name already
        # exists. The document title is the intentional user-facing label and
        # must not expose those storage implementation details.
        title = self.title.strip().replace("/", "-").replace("\\", "-")
        if title and separator:
            if title.lower().endswith(f".{extension.lower()}"):
                return title
            return f"{title}.{extension}"
        return file_name

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
    def is_editable_spreadsheet(self):
        return self.file_extension == "xlsx"

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


class SpreadsheetRevision(models.Model):
    """A recoverable spreadsheet version created before browser edits."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="spreadsheet_revisions")
    revision = models.PositiveIntegerField()
    file = models.FileField(upload_to="protected/spreadsheet-revisions/", max_length=255)
    saved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-revision"]
        constraints = [
            models.UniqueConstraint(fields=("document", "revision"), name="unique_document_spreadsheet_revision"),
        ]
