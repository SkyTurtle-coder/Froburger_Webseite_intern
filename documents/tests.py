import json
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext, override_settings
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from accounts.models import Role

from .models import Document, DocumentFolder, FolderScope, SpreadsheetRevision
from .policies import can_delete_document, can_download_document, can_edit_document, can_view_document


class DocumentModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tester", password="testpass123")
        cls.general_folder = DocumentFolder.objects.create(name="Allgemein", scope=FolderScope.GENERAL)
        cls.sensitive_folder = DocumentFolder.objects.create(name="Sensibel", scope=FolderScope.SENSITIVE)

    def test_document_scope_must_match_folder_scope(self):
        document = Document(
            title="Falsch",
            folder=self.general_folder,
            visibility=FolderScope.SENSITIVE,
            uploaded_by=self.user,
            file="protected/test.txt",
        )

        with self.assertRaises(ValidationError):
            document.full_clean()

    def test_document_without_folder_is_allowed(self):
        document = Document(
            title="Root",
            folder=None,
            visibility=FolderScope.GENERAL,
            uploaded_by=self.user,
            file="protected/root.txt",
        )

        document.full_clean()

    def test_file_icon_detects_supported_extensions_case_insensitively(self):
        mapping = {
            "blatt.PDF": "pdf",
            "protokoll.doc": "word",
            "protokoll.DOCX": "word",
            "logo.svg": "svg",
            "scan.PNG": "image",
            "bild.jpeg": "image",
            "liste.xlsx": "sheet",
            "folien.pptx": "slides",
            "notiz.txt": "text",
            "datei.bin": "file",
        }

        for file_name, expected_icon in mapping.items():
            with self.subTest(file_name=file_name):
                document = Document(
                    title=file_name,
                    folder=None,
                    visibility=FolderScope.GENERAL,
                    uploaded_by=self.user,
                    file=f"protected/{file_name}",
                )
                self.assertEqual(document.file_icon, expected_icon)


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class DocumentManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_role = Role.objects.get(code="ADMIN")
        cls.bursch_role = Role.objects.get(code="BURSCH")

        cls.uploader = User.objects.create_user(username="uploader-docs", password="testpass123")
        cls.member = User.objects.create_user(username="member-docs", password="testpass123")
        cls.admin = User.objects.create_user(username="admin-docs", password="testpass123")
        cls.admin.profile.roles.add(cls.admin_role)
        cls.sensitive_uploader = User.objects.create_user(username="sensitive-uploader", password="testpass123")
        cls.sensitive_uploader.profile.roles.add(cls.bursch_role)
        cls.bursch = User.objects.create_user(username="bursch-docs", password="testpass123")
        cls.bursch.profile.roles.add(cls.bursch_role)

        cls.root_folder = DocumentFolder.objects.create(name="Archiv", scope=FolderScope.GENERAL)
        cls.child_folder = DocumentFolder.objects.create(name="Protokolle", scope=FolderScope.GENERAL, parent=cls.root_folder)
        cls.alt_folder = DocumentFolder.objects.create(name="Ablage", scope=FolderScope.GENERAL)
        cls.empty_folder = DocumentFolder.objects.create(name="Leer", scope=FolderScope.GENERAL)
        cls.sensitive_folder = DocumentFolder.objects.create(name="Interna", scope=FolderScope.SENSITIVE)

        cls.root_document = Document.objects.create(
            title="Leitfaden",
            description="Root-Dokument",
            folder=None,
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile("leitfaden.txt", b"root"),
            uploaded_by=cls.uploader,
        )
        cls.general_document = Document.objects.create(
            title="Sitzungsprotokoll",
            description="Juli",
            folder=cls.root_folder,
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile("protokoll.txt", b"folder"),
            uploaded_by=cls.uploader,
        )
        cls.general_document_file_name = cls.general_document.file.name
        cls.pdf_document = Document.objects.create(
            title="Statuten",
            description="Ausgabe 2026",
            folder=cls.root_folder,
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile("statuten.pdf", b"%PDF-1.4 sample pdf"),
            uploaded_by=cls.uploader,
        )
        cls.word_document = Document.objects.create(
            title="Bericht",
            description="Word-Datei",
            folder=cls.root_folder,
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile("bericht.DOCX", b"word"),
            uploaded_by=cls.uploader,
        )
        cls.svg_document = Document.objects.create(
            title="Logo",
            description="SVG-Datei",
            folder=cls.root_folder,
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile("logo.svg", b"<svg><script>alert(1)</script></svg>"),
            uploaded_by=cls.uploader,
        )
        cls.png_document = Document.objects.create(
            title="Bild",
            description="PNG-Datei",
            folder=cls.root_folder,
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile("bild.png", b"png"),
            uploaded_by=cls.uploader,
        )
        cls.unknown_document = Document.objects.create(
            title="Daten",
            description="Unbekannt",
            folder=cls.root_folder,
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile("daten.xyz", b"xyz"),
            uploaded_by=cls.uploader,
        )
        cls.nested_document = Document.objects.create(
            title="Traktandenliste",
            description="Unterordner",
            folder=cls.child_folder,
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile("traktanden.txt", b"nested"),
            uploaded_by=cls.uploader,
        )
        cls.sensitive_document = Document.objects.create(
            title="Geheimes Protokoll",
            description="Nur intern",
            folder=cls.sensitive_folder,
            visibility=FolderScope.SENSITIVE,
            file=SimpleUploadedFile("geheim.pdf", b"%PDF-1.4 secret"),
            uploaded_by=cls.sensitive_uploader,
        )
        cls.shared_path_document = Document.objects.create(
            title="Kopie",
            description="Selber Pfad",
            folder=cls.alt_folder,
            visibility=FolderScope.GENERAL,
            file=cls.general_document.file.name,
            uploaded_by=cls.admin,
        )

    def setUp(self):
        self.client.login(username="member-docs", password="testpass123")

    def login_uploader(self):
        self.client.logout()
        self.client.login(username="uploader-docs", password="testpass123")

    def login_admin(self):
        self.client.logout()
        self.client.login(username="admin-docs", password="testpass123")

    def login_sensitive_uploader(self):
        self.client.logout()
        self.client.login(username="sensitive-uploader", password="testpass123")

    def test_policy_functions_enforce_scope_and_ownership(self):
        self.assertTrue(can_view_document(self.member, self.general_document))
        self.assertFalse(can_edit_document(self.member, self.general_document))
        self.assertFalse(can_delete_document(self.member, self.general_document))
        self.assertFalse(can_view_document(self.member, self.sensitive_document))
        self.assertTrue(can_view_document(self.admin, self.sensitive_document))
        self.assertTrue(can_download_document(self.admin, self.sensitive_document))

    def test_documents_and_folders_render_in_single_tree_card(self):
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dokumente und Ordner")
        self.assertNotContains(response, "Ordnerstruktur")

    def test_explanatory_text_is_removed(self):
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertNotContains(response, "Kompakte Baumansicht aller Ordner und Dokumente.")

    def test_ui_uses_correct_german_umlauts(self):
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertContains(response, "Dieser Ordner enthält noch keine Dokumente oder Unterordner.")
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}), {"q": "Archiv"})
        self.assertContains(response, "Zurücksetzen")

    def test_root_documents_render_on_top_level(self):
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        content = response.content.decode()
        self.assertGreater(content.index("Leitfaden"), content.index("Archiv"))

    def test_nested_subfolders_render_recursively(self):
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        content = response.content.decode()
        self.assertLess(content.index("Archiv"), content.index("Protokolle"))
        self.assertLess(content.index("Protokolle"), content.index("Traktandenliste"))

    def test_search_keeps_parent_folder_open(self):
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}), {"q": "Traktanden"})
        self.assertContains(response, "Traktandenliste")
        self.assertContains(response, "<details class=\"document-node\" open", html=False)

    def test_preview_endpoint_returns_inline_pdf(self):
        self.login_uploader()
        response = self.client.get(reverse("document-preview", kwargs={"pk": self.pdf_document.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")

    def test_download_endpoint_returns_attachment(self):
        self.login_uploader()
        response = self.client.get(reverse("document-download", kwargs={"pk": self.pdf_document.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])

    def test_preview_requires_authentication(self):
        self.client.logout()
        response = self.client.get(reverse("document-preview", kwargs={"pk": self.pdf_document.pk}))
        self.assertEqual(response.status_code, 302)

    def test_member_without_permission_cannot_access_sensitive_document(self):
        response = self.client.get(reverse("document-preview", kwargs={"pk": self.sensitive_document.pk}))
        self.assertEqual(response.status_code, 404)

    def test_pdf_documents_render_preview_button(self):
        self.login_uploader()
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertContains(response, reverse("document-preview", kwargs={"pk": self.pdf_document.pk}))
        self.assertContains(response, "Ansehen")

    def test_documents_render_download_button(self):
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertContains(response, "Herunterladen")

    def test_uploader_sees_edit_and_delete_on_own_documents(self):
        self.login_uploader()
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertContains(response, reverse("document-edit", kwargs={"pk": self.general_document.pk}))
        self.assertContains(response, reverse("document-delete", kwargs={"pk": self.general_document.pk}))

    def test_foreign_user_does_not_see_edit_or_delete(self):
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertNotContains(response, reverse("document-edit", kwargs={"pk": self.general_document.pk}))
        self.assertNotContains(response, reverse("document-delete", kwargs={"pk": self.general_document.pk}))

    def test_admin_sees_edit_and_delete_for_all_documents(self):
        self.login_admin()
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertContains(response, reverse("document-edit", kwargs={"pk": self.general_document.pk}))
        self.assertContains(response, reverse("document-delete", kwargs={"pk": self.general_document.pk}))

    def test_delete_dialog_markup_contains_required_text(self):
        self.login_uploader()
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertContains(response, "Abbrechen")
        self.assertContains(response, "Endgültig löschen")
        self.assertContains(response, "data-document-title=\"Sitzungsprotokoll\"", html=False)

    def test_pdf_word_svg_png_and_unknown_icons_render(self):
        self.login_uploader()
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertContains(response, "document-icon--pdf")
        self.assertContains(response, "document-icon--word")
        self.assertContains(response, "document-icon--svg")
        self.assertContains(response, "document-icon--image")
        self.assertContains(response, "document-icon--file")

    def test_uploaded_svg_is_not_embedded_as_markup(self):
        self.login_uploader()
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertNotContains(response, "<svg><script>alert(1)</script></svg>", html=False)

    def test_general_upload_and_folder_creation_forms_remain_available(self):
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertContains(response, "Neuen Ordner erstellen")
        self.assertContains(response, "Dokument hochladen")

    def test_upload_without_folder_still_works(self):
        self.login_uploader()
        response = self.client.post(
            reverse("document-scope", kwargs={"scope": "general"}),
            {
                "action": "upload-document",
                "document-title": "Ohne Ablage",
                "document-description": "Direkt auf Root-Ebene",
                "document-folder": "",
                "document-file": SimpleUploadedFile("ohne-ordner.txt", b"root-upload"),
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Document.objects.filter(title="Ohne Ablage", folder__isnull=True).exists())

    def test_folder_creation_still_works(self):
        self.login_uploader()
        response = self.client.post(
            reverse("document-scope", kwargs={"scope": "general"}),
            {"action": "create-folder", "folder-name": "Neu", "folder-parent": str(self.root_folder.pk)},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(DocumentFolder.objects.filter(name="Neu", parent=self.root_folder).exists())

    def test_scope_page_avoids_excessive_database_queries(self):
        self.login_uploader()
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertEqual(response.status_code, 200)
        # Budget raised from 14 to 16 (SEC-008): SESSION_SAVE_EVERY_REQUEST=True
        # now writes the session on every request (a sliding idle timeout
        # instead of a fixed 14-day expiry) - a couple of extra queries per
        # request is the accepted cost of that security property.
        self.assertLessEqual(len(queries), 16)

    def test_uploader_can_edit_own_general_document(self):
        self.login_uploader()
        response = self.client.post(
            reverse("document-edit", kwargs={"pk": self.general_document.pk}),
            {"title": "Neuer Titel", "description": "Neue Beschreibung", "folder": str(self.alt_folder.pk)},
            follow=True,
        )
        self.general_document.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.general_document.title, "Neuer Titel")
        self.assertEqual(self.general_document.description, "Neue Beschreibung")
        self.assertEqual(self.general_document.folder, self.alt_folder)

    def test_uploader_can_move_document_to_root(self):
        self.login_uploader()
        self.client.post(
            reverse("document-edit", kwargs={"pk": self.general_document.pk}),
            {"title": self.general_document.title, "description": self.general_document.description, "folder": ""},
            follow=True,
        )
        self.general_document.refresh_from_db()
        self.assertIsNone(self.general_document.folder)

    def test_uploader_cannot_move_document_to_other_scope(self):
        self.login_uploader()
        response = self.client.post(
            reverse("document-edit", kwargs={"pk": self.general_document.pk}),
            {"title": self.general_document.title, "description": "", "folder": str(self.sensitive_folder.pk)},
        )
        self.general_document.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["folder"])
        self.assertEqual(self.general_document.folder, self.root_folder)

    def test_uploader_cannot_change_scope_owner_or_file_via_edit(self):
        self.login_uploader()
        self.client.post(
            reverse("document-edit", kwargs={"pk": self.general_document.pk}),
            {
                "title": "Titel bleibt erlaubt",
                "description": "Bearbeitet",
                "folder": str(self.root_folder.pk),
                "visibility": FolderScope.SENSITIVE,
                "uploaded_by": str(self.admin.pk),
                "file": SimpleUploadedFile("hack.pdf", b"x"),
            },
            follow=True,
        )
        self.general_document.refresh_from_db()
        self.assertEqual(self.general_document.visibility, FolderScope.GENERAL)
        self.assertEqual(self.general_document.uploaded_by, self.uploader)
        self.assertEqual(self.general_document.file.name, self.general_document_file_name)

    def test_foreign_user_cannot_edit_document(self):
        response = self.client.get(reverse("document-edit", kwargs={"pk": self.general_document.pk}))
        self.assertEqual(response.status_code, 404)

    def test_admin_can_edit_any_document(self):
        self.login_admin()
        self.client.post(
            reverse("document-edit", kwargs={"pk": self.general_document.pk}),
            {"title": "Admin-Titel", "description": "Admin", "folder": str(self.alt_folder.pk)},
            follow=True,
        )
        self.general_document.refresh_from_db()
        self.assertEqual(self.general_document.title, "Admin-Titel")

    def test_sensitive_uploader_can_edit_only_with_current_sensitive_permission(self):
        self.login_sensitive_uploader()
        response = self.client.post(
            reverse("document-edit", kwargs={"pk": self.sensitive_document.pk}),
            {"title": "Aktualisiert", "description": "Neu", "folder": str(self.sensitive_folder.pk)},
            follow=True,
        )
        self.sensitive_document.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sensitive_document.title, "Aktualisiert")

    def test_sensitive_uploader_without_current_permission_cannot_edit(self):
        self.sensitive_uploader.profile.roles.clear()
        self.login_sensitive_uploader()
        response = self.client.get(reverse("document-edit", kwargs={"pk": self.sensitive_document.pk}))
        self.assertEqual(response.status_code, 404)

    def test_uploader_can_delete_own_general_document(self):
        self.login_uploader()
        file_path = Path(self.pdf_document.file.path)
        response = self.client.post(reverse("document-delete", kwargs={"pk": self.pdf_document.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(pk=self.pdf_document.pk).exists())
        self.assertFalse(file_path.exists())
        self.assertContains(response, "Das Dokument wurde gelöscht.")

    def test_foreign_user_cannot_delete_document(self):
        response = self.client.post(reverse("document-delete", kwargs={"pk": self.general_document.pk}))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Document.objects.filter(pk=self.general_document.pk).exists())

    def test_admin_can_delete_any_document(self):
        self.login_admin()
        response = self.client.post(reverse("document-delete", kwargs={"pk": self.general_document.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(pk=self.general_document.pk).exists())

    def test_sensitive_uploader_can_delete_only_with_current_sensitive_permission(self):
        self.login_sensitive_uploader()
        response = self.client.post(reverse("document-delete", kwargs={"pk": self.sensitive_document.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(pk=self.sensitive_document.pk).exists())

    def test_sensitive_uploader_without_current_permission_cannot_delete(self):
        self.sensitive_uploader.profile.roles.clear()
        self.login_sensitive_uploader()
        response = self.client.post(reverse("document-delete", kwargs={"pk": self.sensitive_document.pk}))
        self.assertEqual(response.status_code, 404)

    def test_delete_via_get_is_not_allowed(self):
        self.login_uploader()
        response = self.client.get(reverse("document-delete", kwargs={"pk": self.general_document.pk}))
        self.assertEqual(response.status_code, 405)

    def test_delete_requires_csrf_protected_post(self):
        self.login_uploader()
        client = Client(enforce_csrf_checks=True)
        client.login(username="uploader-docs", password="testpass123")
        response = client.post(reverse("document-delete", kwargs={"pk": self.general_document.pk}))
        self.assertEqual(response.status_code, 403)

    def test_shared_physical_file_is_not_removed_when_still_referenced(self):
        self.login_uploader()
        shared_path = Path(self.general_document.file.path)
        response = self.client.post(reverse("document-delete", kwargs={"pk": self.general_document.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(shared_path.exists())
        self.assertTrue(Document.objects.filter(pk=self.shared_path_document.pk).exists())

    def test_missing_physical_file_is_handled_cleanly_on_delete(self):
        self.login_uploader()
        missing_document = Document.objects.create(
            title="Fehlt",
            folder=self.root_folder,
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile("fehlt.pdf", b"%PDF-1.4 missing"),
            uploaded_by=self.uploader,
        )
        Path(missing_document.file.path).unlink()
        response = self.client.post(reverse("document-delete", kwargs={"pk": missing_document.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(pk=missing_document.pk).exists())

    def test_missing_document_delete_is_controlled(self):
        self.login_uploader()
        response = self.client.post(reverse("document-delete", kwargs={"pk": 999999}))
        self.assertEqual(response.status_code, 404)

    def test_double_delete_requests_do_not_server_error(self):
        self.login_uploader()
        first = self.client.post(reverse("document-delete", kwargs={"pk": self.root_document.pk}), follow=True)
        second = self.client.post(reverse("document-delete", kwargs={"pk": self.root_document.pk}))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 404)


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class SpreadsheetEditorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="spreadsheet-editor", password="testpass123")
        cls.other_user = User.objects.create_user(username="spreadsheet-reader", password="testpass123")

    def setUp(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Mitglieder"
        sheet["A1"] = "Name"
        sheet["B1"] = "Jahrgang"
        sheet["A2"] = "Max Muster"
        stream = BytesIO()
        workbook.save(stream)
        self.document = Document.objects.create(
            title="Mitgliederliste",
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile(
                "mitglieder.xlsx",
                stream.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            uploaded_by=self.user,
        )
        self.client.login(username="spreadsheet-editor", password="testpass123")

    def _cells(self, value="Max Muster"):
        cells = [["" for _column in range(10)] for _row in range(20)]
        cells[0][0] = "Name"
        cells[0][1] = "Jahrgang"
        cells[1][0] = value
        return cells

    def test_owner_can_open_and_save_xlsx_in_browser(self):
        edit_url = reverse("document-spreadsheet-edit", kwargs={"pk": self.document.pk})
        response = self.client.get(edit_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Max Muster")
        self.assertContains(response, "Zeile hinzufügen")

        response = self.client.post(
            edit_url,
            {"sheet": "Mitglieder", "revision": 0, "cells": json.dumps(self._cells("Anna Beispiel"))},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.document.refresh_from_db()
        self.assertEqual(self.document.spreadsheet_revision, 1)
        self.assertEqual(SpreadsheetRevision.objects.filter(document=self.document).count(), 1)
        with self.document.file.open("rb") as file_handle:
            saved = load_workbook(file_handle)
        self.assertEqual(saved["Mitglieder"]["A2"].value, "Anna Beispiel")

    def test_stale_revision_does_not_overwrite_newer_file(self):
        edit_url = reverse("document-spreadsheet-edit", kwargs={"pk": self.document.pk})
        self.client.post(edit_url, {"sheet": "Mitglieder", "revision": 0, "cells": json.dumps(self._cells("Neu"))})
        response = self.client.post(
            edit_url,
            {"sheet": "Mitglieder", "revision": 0, "cells": json.dumps(self._cells("Veraltet"))},
            follow=True,
        )
        self.assertContains(response, "inzwischen geändert")
        self.document.refresh_from_db()
        with self.document.file.open("rb") as file_handle:
            saved = load_workbook(file_handle)
        self.assertEqual(saved["Mitglieder"]["A2"].value, "Neu")

    def test_non_owner_cannot_open_spreadsheet_editor(self):
        self.client.logout()
        self.client.login(username="spreadsheet-reader", password="testpass123")
        response = self.client.get(reverse("document-spreadsheet-edit", kwargs={"pk": self.document.pk}))
        self.assertEqual(response.status_code, 404)

    def test_untouched_numeric_and_date_cells_keep_their_type(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Daten"
        sheet["A1"] = "Jahrgang"
        sheet["A2"] = 2001
        sheet["B1"] = "Beitritt"
        sheet["B2"] = datetime(2020, 3, 4)
        sheet["C1"] = "Aktiv"
        sheet["C2"] = True
        stream = BytesIO()
        workbook.save(stream)
        document = Document.objects.create(
            title="Typen",
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile(
                "typen.xlsx",
                stream.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            uploaded_by=self.user,
        )
        edit_url = reverse("document-spreadsheet-edit", kwargs={"pk": document.pk})

        cells = [["" for _column in range(10)] for _row in range(20)]
        cells[0][0] = "Jahrgang"
        cells[0][1] = "Beitritt"
        cells[0][2] = "Aktiv"
        cells[1][0] = "2001"
        cells[1][1] = "2020-03-04 00:00:00"
        cells[1][2] = "True"
        cells[1][3] = "2002"  # a genuinely new value in a previously empty cell

        response = self.client.post(
            edit_url,
            {"sheet": "Daten", "revision": 0, "cells": json.dumps(cells)},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        document.refresh_from_db()
        with document.file.open("rb") as file_handle:
            saved = load_workbook(file_handle)
        sheet = saved["Daten"]
        self.assertEqual(sheet["A2"].value, 2001)
        self.assertIsInstance(sheet["A2"].value, int)
        self.assertEqual(sheet["B2"].value, datetime(2020, 3, 4))
        self.assertIs(sheet["C2"].value, True)
        self.assertEqual(sheet["D2"].value, 2002)
        self.assertIsInstance(sheet["D2"].value, int)

    def test_previous_working_file_is_removed_after_save(self):
        edit_url = reverse("document-spreadsheet-edit", kwargs={"pk": self.document.pk})
        original_path = self.document.file.path
        self.assertTrue(Path(original_path).exists())

        self.client.post(edit_url, {"sheet": "Mitglieder", "revision": 0, "cells": json.dumps(self._cells("Erste"))})
        self.document.refresh_from_db()
        first_path = self.document.file.path
        self.assertFalse(Path(original_path).exists())

        self.client.post(
            edit_url,
            {"sheet": "Mitglieder", "revision": 1, "cells": json.dumps(self._cells("Zweite"))},
        )
        self.document.refresh_from_db()
        self.assertFalse(Path(first_path).exists())
        self.assertTrue(Path(self.document.file.path).exists())
        self.assertEqual(SpreadsheetRevision.objects.filter(document=self.document).count(), 2)

    def test_bold_cell_formatting_is_saved_to_excel(self):
        edit_url = reverse("document-spreadsheet-edit", kwargs={"pk": self.document.pk})
        response = self.client.post(
            edit_url,
            {
                "sheet": "Mitglieder",
                "revision": 0,
                "cells": json.dumps(self._cells()),
                "formats": json.dumps([{"row": 1, "column": 1, "bold": True}]),
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.document.refresh_from_db()
        with self.document.file.open("rb") as file_handle:
            saved = load_workbook(file_handle)
        self.assertTrue(saved["Mitglieder"]["A1"].font.bold)

    def test_only_five_spreadsheet_revisions_are_retained(self):
        edit_url = reverse("document-spreadsheet-edit", kwargs={"pk": self.document.pk})
        first_revision_file = ""
        for revision in range(6):
            response = self.client.post(
                edit_url,
                {"sheet": "Mitglieder", "revision": revision, "cells": json.dumps(self._cells(f"Version {revision}"))},
            )
            self.assertEqual(response.status_code, 302)
            if revision == 0:
                first_revision_file = SpreadsheetRevision.objects.get(document=self.document, revision=1).file.name

        revisions = SpreadsheetRevision.objects.filter(document=self.document).order_by("revision")
        self.assertEqual(revisions.count(), 5)
        self.assertEqual(list(revisions.values_list("revision", flat=True)), [2, 3, 4, 5, 6])
        self.assertFalse(default_storage.exists(first_revision_file))

    def test_spreadsheet_file_paths_allow_versioned_long_file_names(self):
        self.assertEqual(Document._meta.get_field("file").max_length, 255)
        self.assertEqual(SpreadsheetRevision._meta.get_field("file").max_length, 255)

    def test_document_file_name_hides_repeated_storage_and_version_prefixes(self):
        document = Document(
            pk=57,
            title="Bestellungen",
            visibility=FolderScope.GENERAL,
            file="protected/spreadsheets/document-57-document-57-document-57-Bestellungen-Version-5.xlsx",
            uploaded_by=self.user,
        )
        self.assertEqual(document.file_name, "Bestellungen.xlsx")

    def test_document_title_is_used_for_storage_suffix_free_file_name(self):
        document = Document(
            pk=57,
            title="Bestellungen",
            visibility=FolderScope.GENERAL,
            file="protected/spreadsheets/document-57-Bestellungen_LmXM61a_00e4q3H.xlsx",
            uploaded_by=self.user,
        )
        self.assertEqual(document.file_name, "Bestellungen.xlsx")


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class DocumentUploadValidationTests(TestCase):
    """SEC-004/SEC-009: general document uploads must be restricted to a
    known-safe allowlist (extension + content-type + magic bytes), with an
    application-level size limit, not just nginx's client_max_body_size."""

    @classmethod
    def setUpTestData(cls):
        cls.uploader = User.objects.create_user(username="upload-validation", password="testpass123")
        cls.folder = DocumentFolder.objects.create(name="Ablage", scope=FolderScope.GENERAL)

    def setUp(self):
        self.client.login(username="upload-validation", password="testpass123")

    def _upload(self, upload):
        return self.client.post(
            reverse("document-scope", kwargs={"scope": "general"}),
            {
                "action": "upload-document",
                "document-title": "Testdokument",
                "document-description": "",
                "document-folder": "",
                "document-file": upload,
            },
            follow=True,
        )

    def test_valid_pdf_is_accepted(self):
        upload = SimpleUploadedFile("statuten.pdf", b"%PDF-1.4 valid content", content_type="application/pdf")
        response = self._upload(upload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Document.objects.filter(title="Testdokument").exists())

    def test_valid_docx_is_accepted(self):
        upload = SimpleUploadedFile(
            "bericht.docx",
            b"PK\x03\x04" + b"0" * 20,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        response = self._upload(upload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Document.objects.filter(title="Testdokument").exists())

    def test_disallowed_extension_is_rejected(self):
        upload = SimpleUploadedFile("script.exe", b"MZ" + b"0" * 20, content_type="application/x-msdownload")
        response = self._upload(upload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(title="Testdokument").exists())
        self.assertContains(response, "Dieser Dateityp ist nicht erlaubt")

    def test_executable_renamed_with_allowed_extension_is_rejected(self):
        # The classic "shell.php.jpg" / "malware.exe renamed to .pdf" attack:
        # extension alone must not be trusted, magic bytes have to match too.
        upload = SimpleUploadedFile("harmless.pdf", b"MZ\x90\x00this-is-actually-an-exe", content_type="application/pdf")
        response = self._upload(upload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(title="Testdokument").exists())
        self.assertContains(response, "Der Inhalt der Datei passt nicht zur Dateiendung")

    def test_php_disguised_as_docx_is_rejected(self):
        upload = SimpleUploadedFile(
            "invoice.docx",
            b"<?php system($_GET['c']); ?>",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        response = self._upload(upload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(title="Testdokument").exists())

    def test_mime_mismatch_is_rejected(self):
        upload = SimpleUploadedFile("statuten.pdf", b"%PDF-1.4 valid content", content_type="image/svg+xml")
        response = self._upload(upload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(title="Testdokument").exists())
        self.assertContains(response, "Der Dateityp der Datei passt nicht zur Dateiendung")

    def test_oversized_file_is_rejected(self):
        from documents.forms import MAX_DOCUMENT_FILE_SIZE

        oversized_content = b"%PDF-1.4 " + (b"0" * (MAX_DOCUMENT_FILE_SIZE + 1))
        upload = SimpleUploadedFile("gross.pdf", oversized_content, content_type="application/pdf")
        response = self._upload(upload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(title="Testdokument").exists())
        self.assertContains(response, "MB gross sein")

    def test_file_without_extension_is_rejected(self):
        upload = SimpleUploadedFile("noextension", b"some content without a dot", content_type="application/octet-stream")
        response = self._upload(upload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(title="Testdokument").exists())
        self.assertContains(response, "Dateiendung")

    def test_empty_file_is_rejected(self):
        # Handled by Django's own FileField validation before clean_file()
        # even runs - included so the behavior stays covered by this test
        # class's expectations if that ever changes.
        upload = SimpleUploadedFile("leer.pdf", b"", content_type="application/pdf")
        response = self._upload(upload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(title="Testdokument").exists())

    def test_generic_octet_stream_content_type_is_still_accepted_with_valid_magic_bytes(self):
        # Some browsers/OSes send application/octet-stream for less common
        # types - shouldn't be treated as a mismatch when the extension and
        # magic bytes both check out.
        upload = SimpleUploadedFile("statuten.pdf", b"%PDF-1.4 valid content", content_type="application/octet-stream")
        response = self._upload(upload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Document.objects.filter(title="Testdokument").exists())

    def test_plain_text_upload_still_works(self):
        # documents/models.py's file_icon and existing usage treat .txt as a
        # first-class supported type - must keep working after this fix.
        upload = SimpleUploadedFile("notiz.txt", b"Freitext ohne Signatur", content_type="text/plain")
        response = self._upload(upload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Document.objects.filter(title="Testdokument").exists())

    def test_binary_payload_renamed_to_txt_is_rejected(self):
        # .txt has no magic-byte signature (unlike pdf/docx/etc.), so this
        # gap - a binary payload renamed to .txt sailing through unchecked -
        # needed its own dedicated content check.
        upload = SimpleUploadedFile("notiz.txt", b"MZ\x90\x00\x00\x00\xffbinary-content", content_type="text/plain")
        response = self._upload(upload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(title="Testdokument").exists())
        self.assertContains(response, "Der Inhalt der Datei passt nicht zur Dateiendung")

    def test_utf8_text_with_umlauts_is_accepted_as_txt(self):
        upload = SimpleUploadedFile("notiz.txt", "Protokoll mit Umlauten: äöü ß".encode("utf-8"), content_type="text/plain")
        response = self._upload(upload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Document.objects.filter(title="Testdokument").exists())
