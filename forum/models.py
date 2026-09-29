from uuid import uuid4

from django.conf import settings
from django.db import models
from django.urls import reverse


def issue_pdf_path(instance, filename):
    return f"protected/forum/{uuid4().hex}.pdf"


class Issue(models.Model):
    title = models.CharField("Titel", max_length=200)
    description = models.TextField("Beschreibung", max_length=10000)
    pdf = models.FileField("PDF-Ausgabe", upload_to=issue_pdf_path, max_length=255)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="forum_issues")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Forum-Ausgabe"
        verbose_name_plural = "Forum-Ausgaben"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("forum:detail", args=[self.pk])


class Comment(models.Model):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="forum_comments")
    body = models.TextField("Kommentar", max_length=5000)
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="direct_replies")
    # Flat threads retain the direct recipient without unbounded visual nesting.
    thread = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies")
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    def get_absolute_url(self):
        return reverse("forum:comment-link", args=[self.pk])


class CommentLike(models.Model):
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="forum_likes")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["comment", "user"], name="forum_unique_comment_like")]
