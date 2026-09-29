import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Role
from .forms import IssueForm
from .models import Comment, CommentLike, Issue


def pdf_upload(name="forum.pdf", content=b"%PDF-1.4\n%%EOF"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ForumTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = User.objects.create_user("forum-member", email="member@example.com")
        cls.other = User.objects.create_user("forum-other", email="other@example.com")
        cls.webx = User.objects.create_user("forum-webx", email="webx@example.com")
        cls.admin = User.objects.create_user("forum-admin", email="admin@example.com")
        for user, vulgo in ((cls.member, "Newton"), (cls.other, "Orion"), (cls.webx, "Atlas"), (cls.admin, "Merkur")):
            user.profile.vulgo = vulgo
            user.profile.save()
        cls.webx.profile.roles.add(Role.objects.get(code="WEB_X"))
        cls.admin.profile.roles.add(Role.objects.get(code="ADMIN"))

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.issue = Issue.objects.create(title="Forum Herbst", description="Unsere neue Ausgabe", pdf=pdf_upload(), author=self.webx)
        self.comment = Comment.objects.create(issue=self.issue, author=self.member, body="Sehr lesenswert!")
        self.client.force_login(self.member)

    def test_all_read_endpoints_require_login(self):
        self.client.logout()
        for name, args in (("list", []), ("detail", [self.issue.pk]), ("pdf", [self.issue.pk]), ("comment-link", [self.comment.pk])):
            with self.subTest(name=name):
                response = self.client.get(reverse(f"forum:{name}", args=args))
                self.assertEqual(response.status_code, 302)
                self.assertIn("/accounts/login/", response.url)

    def test_navigation_and_member_reader(self):
        response = self.client.get(self.issue.get_absolute_url())
        self.assertContains(response, 'href="/forum/"')
        self.assertContains(response, "Newton")
        self.assertContains(response, "PDF herunterladen")
        self.assertContains(response, "data-pdf-reader")
        self.assertNotContains(response, "Ausgabe bearbeiten")

    def test_member_cannot_create_edit_or_delete_issues(self):
        for name, args in (("create", []), ("edit", [self.issue.pk]), ("delete", [self.issue.pk])):
            for method in (self.client.get, self.client.post):
                with self.subTest(name=name, method=method):
                    self.assertEqual(method(reverse(f"forum:{name}", args=args)).status_code, 403)
        self.assertTrue(Issue.objects.filter(pk=self.issue.pk).exists())

    def test_managers_can_publish(self):
        for user in (self.webx, self.admin):
            self.client.force_login(user)
            response = self.client.post(reverse("forum:create"), {"title": "Neue Ausgabe", "description": "Beschreibung", "pdf": pdf_upload()})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(Issue.objects.order_by("-pk").first().author, user)

    def test_pdf_is_private_inline_and_downloadable(self):
        url = reverse("forum:pdf", args=[self.issue.pk])
        for suffix, disposition in (("", "inline"), ("?download=1", "attachment")):
            response = self.client.get(url + suffix)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertIn(disposition, response["Content-Disposition"])
            self.assertIn("private", response["Cache-Control"])
            self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
            self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF-"))
            response.close()

    def test_invalid_pdf_and_missing_description_are_rejected(self):
        for upload in (pdf_upload("fake.html"), pdf_upload(content=b"<script>oops</script>")):
            form = IssueForm({"title": "Test", "description": "Text"}, {"pdf": upload})
            self.assertFalse(form.is_valid())
            self.assertIn("pdf", form.errors)
        form = IssueForm({"title": "Test"}, {"pdf": pdf_upload()})
        self.assertFalse(form.is_valid())
        self.assertIn("description", form.errors)

    def test_oversized_pdf_is_rejected(self):
        upload = pdf_upload()
        upload.size = 20 * 1024 * 1024 + 1
        form = IssueForm({"title": "Test", "description": "Text"}, {"pdf": upload})
        self.assertFalse(form.is_valid())
        self.assertIn("pdf", form.errors)

    def test_pdf_can_be_kept_or_replaced(self):
        self.client.force_login(self.webx)
        old_name = self.issue.pdf.name
        url = reverse("forum:edit", args=[self.issue.pk])
        self.assertEqual(self.client.post(url, {"title": "Korrigiert", "description": "Text"}).status_code, 302)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.pdf.name, old_name)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {"title": "Neu", "description": "Text", "pdf": pdf_upload()})
        self.assertEqual(response.status_code, 302)
        self.issue.refresh_from_db()
        self.assertNotEqual(self.issue.pdf.name, old_name)
        self.assertFalse(Path(self.media.name, old_name).exists())

    def test_member_posts_plain_text_without_spoofing_author(self):
        response = self.client.post(reverse("forum:comment-create", args=[self.issue.pk]), {"body": "<script>alert(1)</script>", "author": self.admin.pk})
        self.assertEqual(response.status_code, 302)
        comment = Comment.objects.latest("pk")
        self.assertEqual(comment.author, self.member)
        self.assertContains(self.client.get(self.issue.get_absolute_url()), "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertEqual(len(mail.outbox), 0)

    def test_empty_and_long_comments_are_rejected(self):
        for body in ("   ", "a" * 5001):
            response = self.client.post(reverse("forum:comment-create", args=[self.issue.pk]), {"body": body})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(Comment.objects.count(), 1)

    def test_reply_sends_email_to_direct_recipient_after_commit(self):
        self.client.force_login(self.other)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("forum:comment-create", args=[self.issue.pk]), {"body": "Danke, Newton!", "parent": self.comment.pk})
        self.assertEqual(response.status_code, 302)
        reply = Comment.objects.latest("pk")
        self.assertEqual(reply.thread, self.comment)
        self.assertEqual(reply.parent, self.comment)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.member.email])
        self.assertIn("Orion", mail.outbox[0].body)
        self.assertIn(reply.get_absolute_url(), mail.outbox[0].body)
        self.client.force_login(self.webx)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("forum:comment-create", args=[self.issue.pk]), {"body": "Antwort auf die Antwort", "parent": reply.pk})
        nested = Comment.objects.latest("pk")
        self.assertEqual(nested.thread, self.comment)
        self.assertEqual(mail.outbox[-1].to, [self.other.email])
        self.assertContains(self.client.get(self.issue.get_absolute_url()), "Antwort auf die Antwort")

    def test_self_reply_does_not_send_email(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("forum:comment-create", args=[self.issue.pk]), {"body": "Nachtrag", "parent": self.comment.pk})
        self.assertEqual(len(mail.outbox), 0)

    def test_mail_failure_does_not_lose_reply(self):
        self.client.force_login(self.other)
        with patch("forum.services.send_mail", side_effect=OSError("SMTP unavailable")), self.assertLogs("forum.services", level="ERROR"), self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("forum:comment-create", args=[self.issue.pk]), {"body": "Bleibt gespeichert", "parent": self.comment.pk})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Comment.objects.filter(body="Bleibt gespeichert").exists())

    def test_cross_issue_and_invalid_parent_are_rejected(self):
        other_issue = Issue.objects.create(title="Andere", description="Text", pdf=pdf_upload(), author=self.admin)
        for parent in (self.comment.pk, "abc"):
            response = self.client.post(reverse("forum:comment-create", args=[other_issue.pk]), {"body": "Falsch", "parent": parent})
            self.assertEqual(response.status_code, 404)

    def test_edit_marks_timestamp_and_preserves_author(self):
        url = reverse("forum:comment-edit", args=[self.comment.pk])
        self.client.post(url, {"body": self.comment.body})
        self.comment.refresh_from_db()
        self.assertIsNone(self.comment.edited_at)
        self.client.post(url, {"body": "Geändert", "author": self.admin.pk})
        self.comment.refresh_from_db()
        self.assertIsNotNone(self.comment.edited_at)
        self.assertEqual(self.comment.author, self.member)
        self.assertContains(self.client.get(self.issue.get_absolute_url()), "Bearbeitet am")

    def test_other_members_cannot_modify_comments(self):
        self.client.force_login(self.other)
        for name in ("comment-edit", "comment-delete"):
            self.assertEqual(self.client.post(reverse(f"forum:{name}", args=[self.comment.pk]), {"body": "Fremd"}).status_code, 403)

    def test_managers_can_moderate_comments(self):
        for user in (self.webx, self.admin):
            self.client.force_login(user)
            self.assertEqual(self.client.post(reverse("forum:comment-edit", args=[self.comment.pk]), {"body": user.username}).status_code, 302)
        self.assertEqual(self.client.post(reverse("forum:comment-delete", args=[self.comment.pk])).status_code, 302)

    def test_deleting_comment_preserves_replies_and_removes_likes(self):
        reply = Comment.objects.create(issue=self.issue, author=self.other, body="Antwort bleibt", parent=self.comment, thread=self.comment)
        CommentLike.objects.create(comment=self.comment, user=self.other)
        self.client.post(reverse("forum:comment-delete", args=[self.comment.pk]))
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.body, "")
        self.assertIsNotNone(self.comment.deleted_at)
        self.assertTrue(Comment.objects.filter(pk=reply.pk).exists())
        self.assertEqual(self.comment.likes.count(), 0)
        response = self.client.get(self.issue.get_absolute_url())
        self.assertContains(response, "Dieser Kommentar wurde gelöscht")
        self.assertContains(response, "Antwort bleibt")
        self.assertEqual(self.client.post(reverse("forum:comment-like", args=[self.comment.pk]), {"liked": "1"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("forum:comment-create", args=[self.issue.pk]), {"body": "Neu", "parent": self.comment.pk}).status_code, 404)

    def test_like_is_unique_idempotent_and_reversible(self):
        url = reverse("forum:comment-like", args=[self.comment.pk])
        for _ in range(2):
            self.assertEqual(self.client.post(url, {"liked": "1"}).status_code, 302)
        self.assertEqual(self.comment.likes.count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CommentLike.objects.create(comment=self.comment, user=self.member)
        self.client.post(url, {"liked": "0"})
        self.assertEqual(self.comment.likes.count(), 0)

    def test_sort_by_likes_then_newest_and_paginate_permalink(self):
        newest = Comment.objects.create(issue=self.issue, author=self.other, body="Neu")
        CommentLike.objects.create(comment=self.comment, user=self.other)
        response = self.client.get(self.issue.get_absolute_url())
        self.assertEqual([c.pk for c in response.context["page_obj"]], [self.comment.pk, newest.pk])
        self.comment.likes.all().delete()
        response = self.client.get(self.issue.get_absolute_url())
        self.assertEqual([c.pk for c in response.context["page_obj"]], [newest.pk, self.comment.pk])
        for i in range(15):
            Comment.objects.create(issue=self.issue, author=self.other, body=f"Kommentar {i}")
        link = self.client.get(self.comment.get_absolute_url())
        self.assertIn("?page=2#comment-", link.url)
        self.assertContains(self.client.get(link.url), self.comment.body)

    def test_issue_deletion_removes_thread_and_file(self):
        self.client.force_login(self.admin)
        reply = Comment.objects.create(issue=self.issue, author=self.other, body="Antwort", parent=self.comment, thread=self.comment)
        Comment.objects.create(issue=self.issue, author=self.other, body="Weiter", parent=reply, thread=self.comment)
        name = self.issue.pdf.name
        url = reverse("forum:delete", args=[self.issue.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(Issue.objects.filter(pk=self.issue.pk).exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(Comment.objects.count(), 0)
        self.assertFalse(Path(self.media.name, name).exists())

    def test_mutations_require_post_and_csrf(self):
        self.assertEqual(self.client.get(reverse("forum:comment-like", args=[self.comment.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse("forum:comment-create", args=[self.issue.pk])).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.member)
        response = csrf_client.post(reverse("forum:comment-create", args=[self.issue.pk]), {"body": "Ohne Token"})
        self.assertEqual(response.status_code, 403)
