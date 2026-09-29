"""Optional real-browser check: manage.py test forum.tests_browser --noinput."""
import importlib.util
import os
import tempfile
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from accounts.models import Role
from .models import Comment, Issue


@skipUnless(importlib.util.find_spec("playwright"), "Optional Playwright installation required")
@override_settings(
    SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
)
class ForumBrowserTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        # Shut the live server down before deleting PDFs it may still stream.
        cls.media = cls.enterClassContext(tempfile.TemporaryDirectory())
        cls.enterClassContext(override_settings(MEDIA_ROOT=cls.media))
        super().setUpClass()

    def test_pdf_and_discussion_desktop_and_mobile(self):
        from playwright.sync_api import sync_playwright

        # Playwright's sync bridge runs an event loop; ORM calls here are still
        # sequential and use this test's isolated database only.
        with patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"}), sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
            page = context.new_page()
            page.set_content('<html><body><h1>Forum Herbst 2026</h1><p>Unsere Verbindung im Gespraech.</p><div style="break-before:page"><h1>Zweite Seite</h1><p>Mitteilungen und Termine.</p></div></body></html>')
            pdf = page.pdf(format="A4")
            manager = User.objects.create_user("browser-webx", email="webx@example.com")
            manager.profile.vulgo = "Atlas"
            manager.profile.save()
            manager.profile.roles.add(Role.objects.get(code="WEB_X"))
            member = User.objects.create_user("browser-member", email="member@example.com")
            member.profile.vulgo = "Newton"
            member.profile.save()
            self.client.force_login(manager)
            context.add_cookies([{"name": "sessionid", "value": self.client.cookies["sessionid"].value, "url": self.live_server_url}])
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + "/forum/neu/")
            page.wait_for_load_state("networkidle")
            page.get_by_label("Titel", exact=True).fill("Forum Herbst 2026")
            page.get_by_label("Beschreibung", exact=True).fill("Gemeinsam zurückblicken, Neues entdecken und im Gespräch bleiben.")
            page.get_by_label("PDF-Ausgabe", exact=True).set_input_files({"name": "herbst.pdf", "mimeType": "application/pdf", "buffer": pdf})
            page.get_by_role("button", name="Veröffentlichen", exact=True).click()
            page.wait_for_selector('[data-pdf-reader][data-rendered="1"]')
            self.assertEqual(page.locator('[data-text]').inner_text().strip().splitlines()[0], "Forum Herbst 2026")
            page.get_by_role("button", name="Nächste PDF-Seite").click()
            page.wait_for_selector('[data-pdf-reader][data-rendered="2"]')
            self.assertIn("Zweite Seite", page.locator('[data-text]').inner_text())
            page.get_by_label("PDF-Zoom").select_option("1.5")
            page.wait_for_function("parseFloat(document.querySelector('[data-canvas]').style.width) > 850")
            page.get_by_label("PDF-Zoom").select_option("fit")
            page.get_by_role("button", name="Vorherige PDF-Seite").click()
            page.wait_for_selector('[data-pdf-reader][data-rendered="1"]')
            page.get_by_label("Kommentar", exact=True).fill("Was hat euch an dieser Ausgabe besonders gefallen?")
            page.get_by_role("button", name="Kommentar veröffentlichen", exact=True).click()
            page.wait_for_url("**#comment-*")
            page.wait_for_load_state("networkidle")
            issue = Issue.objects.get()
            root = Comment.objects.get()
            self.client.force_login(member)
            context.add_cookies([{"name": "sessionid", "value": self.client.cookies["sessionid"].value, "url": self.live_server_url}])
            page.goto(self.live_server_url + issue.get_absolute_url())
            page.wait_for_load_state("networkidle")
            page.get_by_role("button", name="Kommentar liken").click()
            page.wait_for_url("**#comment-*")
            page.wait_for_load_state("networkidle")
            self.assertEqual(root.likes.count(), 1)
            page.locator("summary", has_text="Atlas antworten").click()
            page.get_by_label("Deine Antwort", exact=True).fill("Der Rückblick auf unsere Anlässe!")
            page.get_by_role("button", name="Antwort veröffentlichen", exact=True).click()
            page.wait_for_url("**#comment-*")
            page.wait_for_load_state("networkidle")
            self.assertEqual(len(mail.outbox), 1)
            self.assertEqual(mail.outbox[0].to, [manager.email])
            reply = Comment.objects.exclude(pk=root.pk).get()
            page.locator(f"#comment-{reply.pk}").get_by_role("link", name="Bearbeiten", exact=True).click()
            page.get_by_label("Kommentar", exact=True).fill("Der Rückblick auf unsere gemeinsamen Anlässe!")
            page.get_by_role("button", name="Änderungen speichern").click()
            page.wait_for_url("**#comment-*")
            page.wait_for_load_state("networkidle")
            self.assertIn("Bearbeitet am", page.locator(f"#comment-{reply.pk}").inner_text())
            self.assertEqual(page.get_by_role("link", name="Ausgabe bearbeiten").count(), 0)
            artifacts = Path(tempfile.gettempdir()) / "avf-forum-preview"
            artifacts.mkdir(exist_ok=True)
            page.goto(self.live_server_url + issue.get_absolute_url())
            page.wait_for_load_state("networkidle")
            page.wait_for_selector('[data-pdf-reader][data-rendered="1"]')
            page.screenshot(path=str(artifacts / "desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.reload()
            page.wait_for_load_state("networkidle")
            page.wait_for_selector('[data-pdf-reader][data-rendered="1"]')
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
            self.assertLessEqual(page.locator('[data-canvas]').bounding_box()["width"], 390)
            page.screenshot(path=str(artifacts / "mobile.png"), full_page=True)
            with page.expect_download() as download:
                page.get_by_role("link", name="PDF herunterladen", exact=True).click()
            self.assertEqual(Path(download.value.path()).read_bytes(), pdf)
            self.assertEqual(errors, [])
            print(f"\nForum browser previews: {artifacts}")
            context.close()
            browser.close()
