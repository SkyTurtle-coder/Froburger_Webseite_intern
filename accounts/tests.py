import io
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from textwrap import dedent
from unittest import skip

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from PIL import Image

from accounts import throttling
from accounts.auth_backends import EmailOrVulgoBackend
from accounts.management.commands.sync_public_members_page import validate_public_member_media_urls
from accounts.models import MemorialEntry, Profile, Role
from accounts.public_members import build_public_members_payload, is_public_member
from accounts.public_media import get_public_media_base_url
from documents.models import Document, DocumentFolder, FolderScope
from events.models import Event


class PermissionFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_role = Role.objects.get(code="ADMIN")
        cls.webx_role = Role.objects.get(code="WEB_X")
        cls.bursch_role = Role.objects.get(code="BURSCH")
        cls.altfroburger_role = Role.objects.get(code="ALTFROBURGER")
        cls.af_president_role = Role.objects.get(code="AF_PRAESIDENT")

        cls.admin = User.objects.create_user(username="admin", password="testpass123")
        cls.admin.profile.roles.add(cls.admin_role)

        cls.webx = User.objects.create_user(username="webx", password="testpass123")
        cls.webx.profile.roles.add(cls.webx_role)

        cls.bursch = User.objects.create_user(username="bursch", password="testpass123")
        cls.bursch.profile.roles.add(cls.bursch_role)

        cls.member = User.objects.create_user(username="member", password="testpass123")

        cls.af_member = User.objects.create_user(username="afmember", password="testpass123")
        cls.af_member.profile.first_name = "Anton"
        cls.af_member.profile.last_name = "Froburger"
        cls.af_member.profile.vulgo = "Cerevis"
        cls.af_member.profile.save()
        cls.af_member.profile.roles.add(cls.altfroburger_role, cls.af_president_role)

        cls.general_folder = DocumentFolder.objects.create(name="Allgemein", scope=FolderScope.GENERAL)
        cls.sensitive_folder = DocumentFolder.objects.create(name="Sensibel", scope=FolderScope.SENSITIVE)

        cls.general_document = Document.objects.create(
            title="Mitteilungsblatt",
            folder=cls.general_folder,
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile("blatt.txt", b"general"),
            uploaded_by=cls.admin,
        )
        cls.sensitive_document = Document.objects.create(
            title="Protokoll",
            folder=cls.sensitive_folder,
            visibility=FolderScope.SENSITIVE,
            file=SimpleUploadedFile("protokoll.txt", b"sensitive"),
            uploaded_by=cls.admin,
        )

        start = timezone.now() + timedelta(days=10)
        end = start + timedelta(hours=4)

        cls.event = Event.objects.create(
            title="Stammabend",
            description="Intern",
            start=start,
            end=end,
            location="Basel",
            status="INTERN",
        )
        cls.public_event = Event.objects.create(
            title="Oeffentlicher Komm",
            short_description="Fuer die API sichtbar",
            description="Oeffentlich",
            start=start,
            end=end,
            location="Liestal",
            status="OFF",
            is_public=True,
        )
        cls.past_public_event = Event.objects.create(
            title="Vergangener Anlass",
            short_description="Schon vorbei",
            description="Vergangen",
            start=timezone.make_aware(datetime(2026, 7, 1, 18, 0)),
            end=timezone.make_aware(datetime(2026, 7, 1, 22, 0)),
            location="Basel",
            status="HOCHOFF",
            is_public=True,
        )

    def test_non_admin_cannot_access_profile_admin_area(self):
        self.client.login(username="member", password="testpass123")
        response = self.client.get(reverse("profile-list"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_profile_admin_area(self):
        self.client.login(username="admin", password="testpass123")
        response = self.client.get(reverse("profile-list"))
        self.assertEqual(response.status_code, 200)

    def test_member_can_access_member_directory(self):
        self.client.login(username="member", password="testpass123")
        response = self.client.get(reverse("member-directory"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.admin.username)
        self.assertContains(response, self.member.username)

    def test_member_cannot_access_events(self):
        self.client.login(username="member", password="testpass123")
        response = self.client.get(reverse("event-list"))
        self.assertEqual(response.status_code, 403)

    def test_webx_can_access_events(self):
        self.client.login(username="webx", password="testpass123")
        response = self.client.get(reverse("event-list"))
        self.assertEqual(response.status_code, 200)

    def test_general_documents_visible_to_any_logged_in_user(self):
        self.client.login(username="member", password="testpass123")
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.general_document.title)

    def test_sensitive_documents_hidden_from_regular_member(self):
        self.client.login(username="member", password="testpass123")
        response = self.client.get(reverse("document-scope", kwargs={"scope": "sensitive"}))
        self.assertEqual(response.status_code, 404)

    def test_sensitive_documents_visible_to_bursch(self):
        self.client.login(username="bursch", password="testpass123")
        response = self.client.get(reverse("document-scope", kwargs={"scope": "sensitive"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.sensitive_document.title)

    def test_sensitive_documents_visible_to_altfroburger(self):
        self.client.login(username="afmember", password="testpass123")
        response = self.client.get(reverse("document-scope", kwargs={"scope": "sensitive"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.sensitive_document.title)

    def test_sensitive_download_blocked_for_member(self):
        self.client.login(username="member", password="testpass123")
        response = self.client.get(reverse("document-download", kwargs={"pk": self.sensitive_document.pk}))
        self.assertEqual(response.status_code, 404)

    def test_sensitive_download_allowed_for_admin(self):
        self.client.login(username="admin", password="testpass123")
        response = self.client.get(reverse("document-download", kwargs={"pk": self.sensitive_document.pk}))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_filter_profiles_by_role(self):
        self.client.login(username="admin", password="testpass123")
        response = self.client.get(reverse("profile-list"), {"role": "WEB_X"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.webx.username)
        self.assertNotContains(response, self.member.username)

    def test_admin_profile_form_renders_roles_as_checkboxes(self):
        self.client.login(username="admin", password="testpass123")
        response = self.client.get(reverse("profile-edit", kwargs={"pk": self.webx.profile.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="roles"', html=False)
        self.assertContains(response, 'type="checkbox"', html=False)
        self.assertNotContains(response, '<select name="roles"', html=False)

    def test_admin_profile_form_uses_human_role_labels(self):
        self.client.login(username="admin", password="testpass123")
        response = self.client.get(reverse("profile-edit", kwargs={"pk": self.af_member.profile.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AF-Präsident")
        self.assertContains(response, "Altfroburger")
        self.assertNotContains(response, "AF_PRAESIDENT")
        self.assertNotContains(response, "ALTFROBURGER")

    def test_profile_detail_renders_human_role_labels(self):
        self.client.login(username="admin", password="testpass123")
        response = self.client.get(reverse("profile-detail", kwargs={"pk": self.af_member.profile.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AF-Präsident")
        self.assertContains(response, "Altfroburger")
        self.assertNotContains(response, "AF_PRAESIDENT")
        self.assertNotContains(response, "ALTFROBURGER")

    def test_profile_detail_no_longer_shows_calendar_subscription_section(self):
        self.client.login(username="member", password="testpass123")
        response = self.client.get(reverse("profile-detail", kwargs={"pk": self.member.profile.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Kalenderabonnement")
        self.assertNotContains(response, "Kalenderlink erstellen")

    def test_webx_can_filter_events_by_visibility_and_timing(self):
        self.client.login(username="webx", password="testpass123")
        response = self.client.get(reverse("event-list"), {"visibility": "public", "timing": "upcoming"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.public_event.title)
        self.assertNotContains(response, self.event.title)
        self.assertNotContains(response, self.past_public_event.title)

    def test_member_can_search_general_documents(self):
        self.client.login(username="member", password="testpass123")
        response = self.client.get(reverse("document-scope", kwargs={"scope": "general"}), {"q": "Mitteil"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.general_document.title)

    def test_logged_in_user_can_access_password_change_form(self):
        self.client.login(username="member", password="testpass123")
        response = self.client.get(reverse("password_change"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwort ändern")

    def test_logged_in_user_can_change_password(self):
        self.client.login(username="member", password="testpass123")
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": "testpass123",
                "new_password1": "NeuesPasswort123!",
                "new_password2": "NeuesPasswort123!",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwort aktualisiert")
        self.client.logout()
        self.assertTrue(self.client.login(username="member", password="NeuesPasswort123!"))

    def test_public_members_api_includes_af_committee_and_altfroburger_sections(self):
        response = self.client.get(reverse("api-v1-public-members"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertIn("sections", payload)
        self.assertIn("af_committee", payload["sections"])
        self.assertIn("altfroburger", payload["sections"])

        af_members = payload["sections"]["af_committee"]["members"]
        altfroburger_members = payload["sections"]["altfroburger"]["members"]

        self.assertTrue(any(member["display_name"] == "Anton Froburger" for member in af_members))
        self.assertTrue(any(member["display_name"] == "Anton Froburger" for member in altfroburger_members))
        anton = next(member for member in af_members if member["display_name"] == "Anton Froburger")
        self.assertEqual([role["label"] for role in anton["roles"]], ["AF-Präsident"])


@override_settings(PUBLIC_MEDIA_BASE_URL="https://media.avfroburger.test/media/")
class PublicMembersPayloadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.senior_role = Role.objects.get(code="SENIOR")
        cls.webx_role = Role.objects.get(code="WEB_X")
        cls.bursch_role = Role.objects.get(code="BURSCH")

        cls.committee_user = User.objects.create_user(username="committee", password="testpass123")
        cls.committee_user.profile.first_name = "Max"
        cls.committee_user.profile.last_name = "Muster"
        cls.committee_user.profile.vulgo = "Vector"
        cls.committee_user.profile.entry_year = 2022
        cls.committee_user.profile.entry_semester = Profile.Semester.HERBSTSEMESTER
        cls.committee_user.profile.academic_title = "MSc"
        cls.committee_user.profile.degree_program = "Biotechnology"
        cls.committee_user.profile.save()
        cls.committee_user.profile.roles.add(cls.senior_role, cls.webx_role, cls.bursch_role)

        cls.no_photo_user = User.objects.create_user(username="nophoto", password="testpass123")
        cls.no_photo_user.profile.first_name = "Nina"
        cls.no_photo_user.profile.last_name = "Ohnebild"
        cls.no_photo_user.profile.save()
        cls.no_photo_user.profile.roles.add(cls.bursch_role)

        cls.special_user = User.objects.create_user(username="specialmember", password="testpass123")
        cls.special_user.profile.first_name = "Zoë"
        cls.special_user.profile.last_name = "Äther"
        cls.special_user.profile.vulgo = "Ätna"
        cls.special_user.profile.degree_program = "Life Sciences & Biotech"
        cls.special_user.profile.save()
        cls.special_user.profile.roles.add(cls.bursch_role)

        cls.deceased_user = User.objects.create_user(username="deceasedmember", password="testpass123")
        cls.deceased_user.profile.first_name = "Vera"
        cls.deceased_user.profile.last_name = "Vergangen"
        cls.deceased_user.profile.death_date = datetime(2026, 7, 17).date()
        cls.deceased_user.profile.save()
        cls.deceased_user.profile.roles.add(cls.bursch_role)

    def setUp(self):
        cache.clear()  # avoid SEC-013's per-IP rate limit tripping across tests in this class

    def test_public_media_base_url_requires_http_scheme(self):
        with override_settings(PUBLIC_MEDIA_BASE_URL="media.avfroburger.test/media/"):
            with self.assertRaises(ImproperlyConfigured):
                get_public_media_base_url()

    @override_settings(ALLOWED_HOSTS=["testserver", "evil.example.test"])
    def test_public_members_api_ignores_unexpected_host_header(self):
        response = self.client.get(reverse("api-v1-public-members"), HTTP_HOST="evil.example.test")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        committee_member = payload["sections"]["committee"]["members"][0]
        self.assertTrue(committee_member["photo"]["fallback"])

    def test_payload_has_schema_version_and_content_hash(self):
        payload = build_public_members_payload()
        self.assertEqual(payload["schema_version"], 2)
        self.assertIn("generated_at", payload)
        self.assertRegex(payload["content_hash"], r"^[0-9a-f]{64}$")

    def test_committee_member_is_deduplicated_and_roles_are_sorted(self):
        payload = build_public_members_payload()
        members = payload["sections"]["committee"]["members"]

        self.assertEqual(len(members), 1)
        self.assertEqual(members[0]["display_name"], "Max Muster")
        self.assertEqual(
            [role["label"] for role in members[0]["roles"]],
            ["Senior"],
        )

    def test_public_payload_includes_only_expected_profile_fields_for_flip_backside(self):
        payload = build_public_members_payload()
        member = payload["sections"]["committee"]["members"][0]

        self.assertEqual(member["first_name"], "Max")
        self.assertEqual(member["last_name"], "Muster")
        self.assertEqual(member["vulgo"], "Vector")
        self.assertEqual(member["entry_year"], 2022)
        self.assertEqual(member["entry_semester"], "HS")
        self.assertEqual(member["entry_display"], "2022 HS")
        self.assertEqual(member["academic_title"], "MSc")
        self.assertEqual(member["degree_program"], "Biotechnology")
        self.assertNotIn("id", member)  # SEC-013: internal PK has no display purpose, never exposed
        self.assertNotIn("birth_date", member)
        self.assertNotIn("death_date", member)
        self.assertNotIn("exit_year", member)
        self.assertNotIn("exit_semester", member)
        self.assertNotIn("email", member)
        self.assertNotIn("phone", member)

    def test_public_payload_handles_missing_extended_fields_without_errors(self):
        payload = build_public_members_payload()
        member = next(member for member in payload["sections"]["salon"]["members"] if member["display_name"] == "Nina Ohnebild")

        self.assertIsNone(member["entry_year"])
        self.assertEqual(member["entry_semester"], "")
        self.assertEqual(member["entry_display"], "")
        self.assertEqual(member["academic_title"], "")
        self.assertEqual(member["degree_program"], "")

    def test_public_payload_preserves_umlauts_and_special_characters(self):
        payload = build_public_members_payload()
        member = next(member for member in payload["sections"]["salon"]["members"] if member["display_name"] == "Zoë Äther")

        self.assertEqual(member["first_name"], "Zoë")
        self.assertEqual(member["last_name"], "Äther")
        self.assertEqual(member["vulgo"], "Ätna")
        self.assertEqual(member["degree_program"], "Life Sciences & Biotech")

    def test_deceased_profiles_are_not_exposed_in_public_members_payload(self):
        payload = build_public_members_payload()
        all_names = [
            member["display_name"]
            for section in payload["sections"].values()
            for member in section["members"]
        ]

        self.assertNotIn("Vera Vergangen", all_names)

    def test_member_without_photo_uses_photo_fallback(self):
        payload = build_public_members_payload()
        salon_members = payload["sections"]["salon"]["members"]
        member = next(member for member in salon_members if member["display_name"] == "Nina Ohnebild")
        self.assertTrue(member["photo"]["fallback"])
        self.assertEqual(member["photo"]["variants"], {})


class PublicMembersApiRateLimitTests(TestCase):
    """SEC-013: moderate per-IP rate limit against direct scraping, without
    blocking WordPress's own (much less frequent) legitimate sync calls."""

    def setUp(self):
        cache.clear()

    def test_requests_within_limit_all_succeed(self):
        from accounts.public_views import PUBLIC_MEMBERS_RATE_LIMIT_MAX

        for _ in range(PUBLIC_MEMBERS_RATE_LIMIT_MAX):
            response = self.client.get(reverse("api-v1-public-members"))
            self.assertEqual(response.status_code, 200)

    def test_requests_beyond_limit_are_throttled(self):
        from accounts.public_views import PUBLIC_MEMBERS_RATE_LIMIT_MAX

        for _ in range(PUBLIC_MEMBERS_RATE_LIMIT_MAX):
            self.client.get(reverse("api-v1-public-members"))

        response = self.client.get(reverse("api-v1-public-members"))
        self.assertEqual(response.status_code, 429)

    def test_different_client_ip_is_not_affected_by_another_ips_throttling(self):
        from accounts.public_views import PUBLIC_MEMBERS_RATE_LIMIT_MAX

        for _ in range(PUBLIC_MEMBERS_RATE_LIMIT_MAX + 1):
            self.client.get(reverse("api-v1-public-members"), REMOTE_ADDR="203.0.113.5")

        response = self.client.get(reverse("api-v1-public-members"), REMOTE_ADDR="203.0.113.9")
        self.assertEqual(response.status_code, 200)


class PublicMemberPhotoDerivativeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bursch_role = Role.objects.get(code="BURSCH")

    def setUp(self):
        self.temp_media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_media_dir.cleanup)

    @override_settings(PUBLIC_MEDIA_BASE_URL="https://intern.avfroburger.test/media/")
    def test_photo_derivatives_are_generated_with_stable_public_urls(self):
        with override_settings(MEDIA_ROOT=self.temp_media_dir.name):
            user = User.objects.create_user(username="photo", password="testpass123")
            profile = user.profile
            profile.first_name = "Petra"
            profile.last_name = "Pixel"
            profile.roles.add(self.bursch_role)
            profile.photo = SimpleUploadedFile("portrait.jpg", self._jpeg_bytes(900, 1200), content_type="image/jpeg")
            profile.save()

            payload = build_public_members_payload()
            member = next(
                member for member in payload["sections"]["salon"]["members"] if member["display_name"] == "Petra Pixel"
            )

            self.assertFalse(member["photo"]["fallback"])
            self.assertEqual(sorted(member["photo"]["variants"].keys()), ["large", "medium", "small"])

            for expected_size_key, expected_size in (("small", 160), ("medium", 320), ("large", 640)):
                variant = member["photo"]["variants"][expected_size_key]
                self.assertEqual(variant["width"], expected_size)
                self.assertEqual(variant["height"], expected_size)
                self.assertTrue(variant["url"].startswith("https://intern.avfroburger.test/media/public/members/"))

            generated_files = list(Path(self.temp_media_dir.name).rglob("*.webp"))
            self.assertEqual(len(generated_files), 3)

    @override_settings(PUBLIC_MEDIA_BASE_URL="https://intern.avfroburger.test/media/")
    def test_missing_photo_file_falls_back_cleanly(self):
        with override_settings(MEDIA_ROOT=self.temp_media_dir.name):
            user = User.objects.create_user(username="broken", password="testpass123")
            profile = user.profile
            profile.first_name = "Bea"
            profile.last_name = "Broken"
            profile.roles.add(self.bursch_role)
            profile.photo = SimpleUploadedFile("portrait.jpg", self._jpeg_bytes(900, 1200), content_type="image/jpeg")
            profile.save()
            Path(profile.photo.path).unlink()

            payload = build_public_members_payload()
            member = next(
                member for member in payload["sections"]["salon"]["members"] if member["display_name"] == "Bea Broken"
            )
            self.assertTrue(member["photo"]["fallback"])

    @override_settings(PUBLIC_MEDIA_BASE_URL="https://intern.avfroburger.test/media/", ALLOWED_HOSTS=["testserver", "evil.example.test"])
    def test_photo_urls_remain_on_configured_public_domain_even_with_different_host(self):
        with override_settings(MEDIA_ROOT=self.temp_media_dir.name):
            user = User.objects.create_user(username="hostindependent", password="testpass123")
            profile = user.profile
            profile.first_name = "Hugo"
            profile.last_name = "Header"
            profile.roles.add(self.bursch_role)
            profile.photo = SimpleUploadedFile("portrait.jpg", self._jpeg_bytes(900, 1200), content_type="image/jpeg")
            profile.save()

            response = self.client.get(reverse("api-v1-public-members"), HTTP_HOST="evil.example.test")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            member = next(
                member for member in payload["sections"]["salon"]["members"] if member["display_name"] == "Hugo Header"
            )
            self.assertTrue(
                member["photo"]["variants"]["medium"]["url"].startswith("https://intern.avfroburger.test/media/public/members/")
            )

    def _jpeg_bytes(self, width, height):
        image = Image.new("RGB", (width, height), color=(40, 120, 80))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
        return buffer.getvalue()


class PublicMemberMediaLifecycleTests(TestCase):
    """SEC-006: cached public photo derivatives must be purged the moment a
    profile stops being publicly listed, using the exact same policy
    (is_public_member) as the public API itself - never the original photo."""

    @classmethod
    def setUpTestData(cls):
        cls.bursch_role = Role.objects.get(code="BURSCH")

    def setUp(self):
        self.temp_media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_media_dir.cleanup)

    def _jpeg_bytes(self, width=600, height=600):
        image = Image.new("RGB", (width, height), color=(10, 80, 200))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    def test_is_public_member_matches_payload_inclusion(self):
        user = User.objects.create_user(username="policy-check", password="testpass123")
        profile = user.profile
        profile.first_name = "Policy"
        profile.last_name = "Check"
        profile.save()

        self.assertFalse(is_public_member(profile))

        profile.roles.add(self.bursch_role)
        self.assertTrue(is_public_member(profile))

        profile.death_date = timezone.now().date()
        profile.save()
        profile.refresh_from_db()
        self.assertFalse(is_public_member(profile))

    @override_settings(PUBLIC_MEDIA_BASE_URL="https://intern.avfroburger.test/media/")
    def test_derivatives_are_purged_when_profile_becomes_deceased(self):
        with override_settings(MEDIA_ROOT=self.temp_media_dir.name):
            user = User.objects.create_user(username="fading", password="testpass123")
            profile = user.profile
            profile.first_name = "Fading"
            profile.last_name = "Member"
            profile.roles.add(self.bursch_role)
            profile.photo = SimpleUploadedFile("portrait.jpg", self._jpeg_bytes(), content_type="image/jpeg")
            profile.save()

            build_public_members_payload()  # forces derivative generation
            derivative_dir = Path(self.temp_media_dir.name) / "public" / "members" / str(profile.pk)
            self.assertTrue(derivative_dir.exists())
            self.assertGreater(len(list(derivative_dir.glob("*.webp"))), 0)

            original_photo_path = Path(profile.photo.path)
            self.assertTrue(original_photo_path.exists())

            with self.captureOnCommitCallbacks(execute=True):
                profile.death_date = timezone.now().date()
                profile.save()

            self.assertFalse(derivative_dir.exists(), "public derivatives must be gone once the profile is deceased")
            self.assertTrue(original_photo_path.exists(), "the original uploaded photo must never be deleted")

    @override_settings(PUBLIC_MEDIA_BASE_URL="https://intern.avfroburger.test/media/")
    def test_derivatives_are_purged_when_public_role_is_removed(self):
        with override_settings(MEDIA_ROOT=self.temp_media_dir.name):
            user = User.objects.create_user(username="rolegone", password="testpass123")
            profile = user.profile
            profile.first_name = "Role"
            profile.last_name = "Gone"
            profile.roles.add(self.bursch_role)
            profile.photo = SimpleUploadedFile("portrait.jpg", self._jpeg_bytes(), content_type="image/jpeg")
            profile.save()

            build_public_members_payload()
            derivative_dir = Path(self.temp_media_dir.name) / "public" / "members" / str(profile.pk)
            self.assertTrue(derivative_dir.exists())

            with self.captureOnCommitCallbacks(execute=True):
                profile.roles.remove(self.bursch_role)
                # M2M changes don't re-trigger post_save on Profile by
                # themselves - save() is what the real admin UI flow does
                # right after changing roles, and is what actually matters
                # here (the signal, not the M2M change itself).
                profile.save()

            self.assertFalse(derivative_dir.exists())

    @override_settings(PUBLIC_MEDIA_BASE_URL="https://intern.avfroburger.test/media/")
    def test_still_public_profile_save_does_not_purge_derivatives(self):
        with override_settings(MEDIA_ROOT=self.temp_media_dir.name):
            user = User.objects.create_user(username="staysvisible", password="testpass123")
            profile = user.profile
            profile.first_name = "Stays"
            profile.last_name = "Visible"
            profile.roles.add(self.bursch_role)
            profile.photo = SimpleUploadedFile("portrait.jpg", self._jpeg_bytes(), content_type="image/jpeg")
            profile.save()

            build_public_members_payload()
            derivative_dir = Path(self.temp_media_dir.name) / "public" / "members" / str(profile.pk)
            self.assertTrue(derivative_dir.exists())

            with self.captureOnCommitCallbacks(execute=True):
                profile.academic_title = "Dr."
                profile.save()

            self.assertTrue(derivative_dir.exists(), "an unrelated profile edit must not purge a still-public member's photo")

    @override_settings(PUBLIC_MEDIA_BASE_URL="https://intern.avfroburger.test/media/")
    def test_becoming_public_again_regenerates_derivatives_on_demand(self):
        with override_settings(MEDIA_ROOT=self.temp_media_dir.name):
            user = User.objects.create_user(username="comeback", password="testpass123")
            profile = user.profile
            profile.first_name = "Come"
            profile.last_name = "Back"
            profile.photo = SimpleUploadedFile("portrait.jpg", self._jpeg_bytes(), content_type="image/jpeg")
            profile.save()  # no public role yet -> not public

            derivative_dir = Path(self.temp_media_dir.name) / "public" / "members" / str(profile.pk)
            self.assertFalse(derivative_dir.exists())

            profile.roles.add(self.bursch_role)
            profile.save()
            build_public_members_payload()

            self.assertTrue(derivative_dir.exists())
            self.assertGreater(len(list(derivative_dir.glob("*.webp"))), 0)


class PurgeStalePublicMemberMediaCommandTests(TestCase):
    def setUp(self):
        self.temp_media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_media_dir.cleanup)

    def test_dry_run_reports_without_deleting(self):
        with override_settings(MEDIA_ROOT=self.temp_media_dir.name):
            stale_dir = Path(self.temp_media_dir.name) / "public" / "members" / "999999"
            stale_dir.mkdir(parents=True)
            (stale_dir / "leftover.webp").write_bytes(b"fake")

            out = io.StringIO()
            call_command("purge_stale_public_member_media", "--dry-run", stdout=out)

            self.assertTrue(stale_dir.exists(), "dry-run must not delete anything")
            self.assertIn("would remove", out.getvalue())
            self.assertIn("999999", out.getvalue())

    def test_real_run_removes_stale_directory_and_keeps_public_one(self):
        with override_settings(MEDIA_ROOT=self.temp_media_dir.name):
            role = Role.objects.get(code="BURSCH")
            user = User.objects.create_user(username="still-public", password="testpass123")
            profile = user.profile
            profile.roles.add(role)
            profile.save()

            public_dir = Path(self.temp_media_dir.name) / "public" / "members" / str(profile.pk)
            public_dir.mkdir(parents=True)
            (public_dir / "keep.webp").write_bytes(b"fake")

            stale_dir = Path(self.temp_media_dir.name) / "public" / "members" / "999999"
            stale_dir.mkdir(parents=True)
            (stale_dir / "leftover.webp").write_bytes(b"fake")

            call_command("purge_stale_public_member_media")

            self.assertFalse(stale_dir.exists())
            self.assertTrue(public_dir.exists())


class PublicMemberSyncGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bursch_role = Role.objects.get(code="BURSCH")

    def setUp(self):
        self.temp_media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_media_dir.cleanup)

    @override_settings(PUBLIC_MEDIA_BASE_URL="https://intern.avfroburger.test/media/")
    def test_sync_guard_accepts_public_https_member_media_urls(self):
        with override_settings(MEDIA_ROOT=self.temp_media_dir.name):
            self._create_member_with_photo("publicok")

            self.assertEqual(validate_public_member_media_urls(), [])

    @override_settings(PUBLIC_MEDIA_BASE_URL="http://127.0.0.1:8000/media/")
    def test_sync_guard_rejects_loopback_member_media_urls(self):
        with override_settings(MEDIA_ROOT=self.temp_media_dir.name):
            self._create_member_with_photo("loopback")

            invalid = validate_public_member_media_urls()

        self.assertTrue(any(reason == "not_https" for _, _, reason in invalid))
        self.assertTrue(any("127.0.0.1:8000/media/public/members/" in url for _, url, _ in invalid))

    @override_settings(PUBLIC_MEDIA_BASE_URL="https://127.0.0.1/media/")
    def test_sync_guard_rejects_private_https_member_media_urls(self):
        with override_settings(MEDIA_ROOT=self.temp_media_dir.name):
            self._create_member_with_photo("privatehost")

            invalid = validate_public_member_media_urls()

        self.assertTrue(any(reason == "private_host" for _, _, reason in invalid))
        self.assertTrue(any("https://127.0.0.1/media/public/members/" in url for _, url, _ in invalid))

    @override_settings(PUBLIC_MEDIA_BASE_URL="https://127.0.0.1/media/")
    def test_sync_guard_can_be_explicitly_overridden_for_local_only_workflows(self):
        with override_settings(MEDIA_ROOT=self.temp_media_dir.name):
            self._create_member_with_photo("override")

            self.assertEqual(validate_public_member_media_urls(allow_private_media_host=True), [])

    def _create_member_with_photo(self, username):
        user = User.objects.create_user(username=username, password="testpass123")
        profile = user.profile
        profile.first_name = "Paula"
        profile.last_name = "Proxy"
        profile.roles.add(self.bursch_role)
        profile.photo = SimpleUploadedFile("portrait.jpg", self._jpeg_bytes(900, 1200), content_type="image/jpeg")
        profile.save()

    def _jpeg_bytes(self, width, height):
        image = Image.new("RGB", (width, height), color=(40, 120, 80))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
        return buffer.getvalue()


class PortalAuthenticationUiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = User.objects.create_user(username="memberuser", password="testpass123")
        cls.member.profile.first_name = "Max"
        cls.member.profile.last_name = "Muster"
        cls.member.profile.vulgo = "Newton"
        cls.member.profile.save()

        cls.special = User.objects.create_user(username="specialuser", password="testpass123")
        cls.special.profile.first_name = "Zoe"
        cls.special.profile.last_name = "Äther"
        cls.special.profile.vulgo = "Ätna/IO"
        cls.special.profile.save()

        cls.admin_role = Role.objects.get(code="ADMIN")
        cls.admin = User.objects.create_user(username="adminlogin", password="testpass123")
        cls.admin.profile.roles.add(cls.admin_role)

        cls.inactive = User.objects.create_user(username="inactiveuser", password="testpass123", is_active=False)
        cls.inactive.profile.vulgo = "Dormant"
        cls.inactive.profile.save()

    def test_login_page_uses_vo_and_public_site_link(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "E-Mail oder Vulgo")
        self.assertContains(response, "Zur Webseite")
        self.assertNotContains(response, "Benutzername")
        self.assertNotContains(response, "WordPress bleibt")

    def test_login_with_correct_vo_and_password_works(self):
        response = self.client.post(reverse("login"), {"username": "Newton", "password": "testpass123"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.member.pk)

    def test_login_with_vo_is_case_insensitive(self):
        response = self.client.post(reverse("login"), {"username": "nEwToN", "password": "testpass123"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.member.pk)

    def test_login_with_vo_ignores_surrounding_whitespace(self):
        response = self.client.post(reverse("login"), {"username": "  Newton  ", "password": "testpass123"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.member.pk)

    def test_login_with_special_character_vo_works(self):
        response = self.client.post(reverse("login"), {"username": "  ätNA/io ", "password": "testpass123"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.special.pk)

    def test_wrong_password_and_unknown_vo_share_same_error_message(self):
        wrong_password = self.client.post(reverse("login"), {"username": "Newton", "password": "wrong"})
        unknown_vo = self.client.post(reverse("login"), {"username": "unknown", "password": "wrong"})

        self.assertContains(wrong_password, "Anmeldung fehlgeschlagen. Bitte prüfe E-Mail oder Vulgo und Passwort.")
        self.assertContains(unknown_vo, "Anmeldung fehlgeschlagen. Bitte prüfe E-Mail oder Vulgo und Passwort.")

    def test_inactive_user_is_rejected(self):
        response = self.client.post(reverse("login"), {"username": "Dormant", "password": "testpass123"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anmeldung fehlgeschlagen. Bitte prüfe E-Mail oder Vulgo und Passwort.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_login_with_username_still_works(self):
        response = self.client.post(reverse("login"), {"username": "adminlogin", "password": "testpass123"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.admin.pk)

    def test_duplicate_vo_values_are_rejected_safely(self):
        duplicate = User.objects.create_user(username="duplicate", password="testpass123")
        duplicate.profile.vulgo = "newton"
        duplicate.profile.save()

        response = self.client.post(reverse("login"), {"username": "Newton", "password": "testpass123"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anmeldung fehlgeschlagen. Bitte prüfe E-Mail oder Vulgo und Passwort.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_dashboard_navigation_contains_dashboard_and_public_site_link(self):
        self.client.login(username="memberuser", password="testpass123")

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard")
        self.assertContains(response, "Zur Webseite")
        self.assertNotContains(response, "WordPress bleibt fuer die oeffentliche Website zustaendig")

    def test_profile_views_use_vo_label(self):
        self.client.login(username="memberuser", password="testpass123")

        detail = self.client.get(reverse("profile-detail", kwargs={"pk": self.member.profile.pk}))
        edit = self.client.get(reverse("profile-edit", kwargs={"pk": self.member.profile.pk}))

        self.assertContains(detail, "v/o")
        self.assertNotContains(detail, ">Vulgo<", html=False)
        self.assertContains(edit, "v/o")
        self.assertNotContains(edit, ">Vulgo<", html=False)


class LoginTimingSideChannelTests(TestCase):
    """SEC-001: an unknown identifier must do the same hashing work as a
    known one, so response time doesn't reveal whether it's registered."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="timinguser", password="testpass123")
        cls.user.profile.vulgo = "Timing"
        cls.user.profile.save()

    def test_unknown_email_still_authenticates_correctly(self):
        # Functional guard: the dummy-hash call must never accidentally
        # allow, deny-incorrectly, or crash the unrelated known-user path.
        self.assertIsNone(
            EmailOrVulgoBackend().authenticate(None, username="nobody@example.com", password="whatever")
        )
        self.assertIsNone(EmailOrVulgoBackend().authenticate(None, username="UnknownVulgo", password="whatever"))
        self.assertIsNotNone(
            EmailOrVulgoBackend().authenticate(None, username="Timing", password="testpass123")
        )
        self.assertIsNone(EmailOrVulgoBackend().authenticate(None, username="Timing", password="wrong"))

    def test_dummy_hasher_runs_same_hasher_as_real_check_password(self):
        # Confirms the mitigation actually performs comparable cryptographic
        # work (not a no-op) without asserting on wall-clock time, which
        # would be flaky in a normal unit-test run.
        dummy_user = User()
        with self.assertNumQueries(0):
            dummy_user.set_password("some-password")
        self.assertTrue(dummy_user.password.startswith("pbkdf2_sha256$"))
        # Same hasher/iteration count as a real stored password, so the two
        # paths cost the same amount of CPU time.
        real_hasher_prefix = self.user.password.split("$")[0]
        self.assertEqual(dummy_user.password.split("$")[0], real_hasher_prefix)

    def test_unknown_and_wrong_password_timing_is_close(self):
        # Separate, tolerant statistical check (not part of normal CI
        # assertions above): averages a few iterations and only fails on a
        # gross regression back to the original ~2x gap the audit measured
        # live (~0.29s vs ~0.53s), not on ordinary noise.
        import time

        def timed_call(identifier, password):
            start = time.perf_counter()
            EmailOrVulgoBackend().authenticate(None, username=identifier, password=password)
            return time.perf_counter() - start

        samples = 5
        unknown_total = sum(timed_call("does-not-exist@example.com", "whatever") for _ in range(samples))
        known_wrong_total = sum(timed_call("Timing", "wrong-password") for _ in range(samples))

        unknown_avg = unknown_total / samples
        known_avg = known_wrong_total / samples

        # Generous tolerance: fails only if the unknown-identifier path is
        # less than half the cost of the known-wrong-password path.
        self.assertGreater(
            unknown_avg,
            known_avg * 0.5,
            f"unknown-identifier login ({unknown_avg:.4f}s) is suspiciously "
            f"faster than known-identifier-wrong-password ({known_avg:.4f}s) "
            "- the dummy password hasher may not be running.",
        )


class LoginRateLimitingTests(TestCase):
    """SEC-002: repeated failed logins must be throttled without ever
    creating a permanent lock or leaking whether an account exists."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="throttleduser", password="testpass123")
        cls.user.profile.vulgo = "Throttled"
        cls.user.profile.save()

        cls.other_user = User.objects.create_user(username="otheruser", password="testpass123")
        cls.other_user.profile.vulgo = "Unrelated"
        cls.other_user.profile.save()

    def setUp(self):
        cache.clear()

    def _fail_login(self, identifier="Throttled", password="wrong"):
        return self.client.post(reverse("login"), {"username": identifier, "password": password})

    def test_limit_engages_after_repeated_failures_for_one_identifier(self):
        for _ in range(throttling.IDENTIFIER_MAX_ATTEMPTS):
            response = self._fail_login()
            self.assertEqual(response.status_code, 200)

        # Even the CORRECT password is now rejected while the identifier is
        # in its cooldown window - the throttle, not the credential, decides.
        response = self.client.post(reverse("login"), {"username": "Throttled", "password": "testpass123"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anmeldung fehlgeschlagen. Bitte prüfe E-Mail oder Vulgo und Passwort.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_throttle_message_is_identical_to_a_normal_failed_login(self):
        for _ in range(throttling.IDENTIFIER_MAX_ATTEMPTS):
            self._fail_login()

        throttled_response = self.client.post(reverse("login"), {"username": "Throttled", "password": "testpass123"})
        normal_failure_response = self.client.post(reverse("login"), {"username": "Unrelated", "password": "wrong"})

        self.assertEqual(
            self._extract_error(throttled_response),
            self._extract_error(normal_failure_response),
        )

    @staticmethod
    def _extract_error(response):
        return response.context["form"].non_field_errors()

    def test_throttling_one_identifier_does_not_block_a_different_account(self):
        for _ in range(throttling.IDENTIFIER_MAX_ATTEMPTS):
            self._fail_login(identifier="Throttled")

        response = self.client.post(reverse("login"), {"username": "Unrelated", "password": "testpass123"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.other_user.pk)

    def test_ip_level_throttle_blocks_spraying_across_many_unknown_identifiers(self):
        for i in range(throttling.IP_MAX_ATTEMPTS):
            self._fail_login(identifier=f"nobody-{i}@example.com")

        # A brand-new identifier, never tried before, is still blocked
        # because the throttle is keyed by source IP as well as identifier.
        response = self.client.post(reverse("login"), {"username": "Throttled", "password": "testpass123"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_successful_login_clears_the_identifier_cooldown(self):
        for _ in range(throttling.IDENTIFIER_MAX_ATTEMPTS - 1):
            self._fail_login()
        # One attempt short of the limit, then a correct login clears the
        # counter (VulgoAuthenticationForm.clean() calls
        # clear_attempts_for_identifier on success)...
        response = self.client.post(reverse("login"), {"username": "Throttled", "password": "testpass123"})
        self.assertEqual(response.status_code, 302)
        self.client.logout()

        # ...so failing almost up to the limit again afterwards must not
        # combine with the earlier attempts to trip it early.
        for _ in range(throttling.IDENTIFIER_MAX_ATTEMPTS - 1):
            self._fail_login()
        response = self.client.post(reverse("login"), {"username": "Throttled", "password": "testpass123"})
        self.assertEqual(response.status_code, 302)

    def test_cooldown_expires_after_its_window(self):
        for _ in range(throttling.IDENTIFIER_MAX_ATTEMPTS):
            self._fail_login()
        self.assertTrue(throttling.is_throttled(None, "throttled"))

        # Simulate the cooldown TTL elapsing (never a permanent lock).
        cache.delete(throttling._cooldown_key("id", "throttled"))
        cache.delete(throttling._attempts_key("id", "throttled"))

        response = self.client.post(reverse("login"), {"username": "Throttled", "password": "testpass123"})
        self.assertEqual(response.status_code, 302)


class PasswordResetRemovedAndSessionPolicyTests(TestCase):
    """SEC-007: the half-wired password-reset flow (routes registered,
    templates missing, no EMAIL_BACKEND) is removed rather than left to 500.
    SEC-008: session lifetime is a deliberate, bounded idle timeout."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="sessionuser", password="testpass123")
        cls.user.profile.vulgo = "SessionCheck"
        cls.user.profile.save()

    def test_password_reset_routes_are_gone_not_broken(self):
        for path in (
            "/accounts/password_reset/",
            "/accounts/password_reset/done/",
            "/accounts/reset/abc/def-token/",
            "/accounts/reset/done/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)

    def test_no_reset_url_names_are_registered(self):
        for name in ("password_reset", "password_reset_done", "password_reset_confirm", "password_reset_complete"):
            with self.subTest(name=name):
                with self.assertRaises(NoReverseMatch):
                    reverse(name)

    def test_login_logout_and_password_change_still_work(self):
        self.assertTrue(reverse("login"))
        self.assertTrue(reverse("logout"))
        self.assertTrue(reverse("password_change"))
        self.assertTrue(reverse("password_change_done"))

        login_response = self.client.post(reverse("login"), {"username": "SessionCheck", "password": "testpass123"})
        self.assertEqual(login_response.status_code, 302)

    def test_session_cookie_age_matches_configured_idle_timeout(self):
        from django.conf import settings as django_settings

        self.client.login(username="sessionuser", password="testpass123")
        self.assertEqual(self.client.session.get_expiry_age(), django_settings.SESSION_COOKIE_AGE)

    def test_session_expiry_slides_forward_on_activity(self):
        self.client.login(username="sessionuser", password="testpass123")
        first_expiry = self.client.session.get_expiry_date()

        # Advance wall-clock time without a real sleep, then make another
        # authenticated request - SESSION_SAVE_EVERY_REQUEST=True should push
        # the expiry forward, proving this is a sliding idle timeout rather
        # than a fixed expiry from login time.
        from unittest.mock import patch

        later = timezone.now() + timedelta(minutes=30)
        with patch("django.utils.timezone.now", return_value=later):
            self.client.get(reverse("dashboard"))
        second_expiry = self.client.session.get_expiry_date()

        self.assertGreater(second_expiry, first_expiry)


class ProfileMembershipModelTests(TestCase):
    def test_profile_without_entry_and_exit_is_valid(self):
        user = User.objects.create_user(username="model-valid", password="testpass123")
        profile = user.profile
        profile.full_clean()

    def test_entry_year_without_semester_is_invalid(self):
        user = User.objects.create_user(username="entry-year", password="testpass123")
        profile = user.profile
        profile.entry_year = 2024
        with self.assertRaises(ValidationError):
            profile.full_clean()

    def test_entry_semester_without_year_is_invalid(self):
        user = User.objects.create_user(username="entry-sem", password="testpass123")
        profile = user.profile
        profile.entry_semester = Profile.Semester.HERBSTSEMESTER
        with self.assertRaises(ValidationError):
            profile.full_clean()

    def test_exit_before_entry_is_invalid(self):
        user = User.objects.create_user(username="exit-before", password="testpass123")
        profile = user.profile
        profile.entry_year = 2025
        profile.entry_semester = Profile.Semester.HERBSTSEMESTER
        profile.exit_year = 2025
        profile.exit_semester = Profile.Semester.FRUEHLINGSSEMESTER
        with self.assertRaises(ValidationError):
            profile.full_clean()

    def test_same_year_entry_fs_and_exit_hs_is_valid(self):
        user = User.objects.create_user(username="entry-fs", password="testpass123")
        profile = user.profile
        profile.entry_year = 2025
        profile.entry_semester = Profile.Semester.FRUEHLINGSSEMESTER
        profile.exit_year = 2025
        profile.exit_semester = Profile.Semester.HERBSTSEMESTER
        profile.full_clean()

    def test_future_birth_date_is_invalid(self):
        user = User.objects.create_user(username="future-birth", password="testpass123")
        profile = user.profile
        profile.birth_date = timezone.localdate() + timedelta(days=1)
        with self.assertRaises(ValidationError):
            profile.full_clean()

    def test_death_date_before_birth_date_is_invalid(self):
        user = User.objects.create_user(username="death-before-birth", password="testpass123")
        profile = user.profile
        profile.birth_date = timezone.localdate() - timedelta(days=100)
        profile.death_date = timezone.localdate() - timedelta(days=200)
        with self.assertRaises(ValidationError):
            profile.full_clean()

    def test_membership_status_priority_prefers_deceased(self):
        user = User.objects.create_user(username="status-priority", password="testpass123")
        profile = user.profile
        profile.exit_year = 2020
        profile.exit_semester = Profile.Semester.FRUEHLINGSSEMESTER
        profile.death_date = timezone.localdate() - timedelta(days=1)
        self.assertEqual(profile.membership_status, Profile.MembershipStatus.VERSTORBEN)


class ProfilePermissionAndMemorialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_role = Role.objects.get(code="ADMIN")
        cls.admin = User.objects.create_user(username="profile-admin", password="testpass123")
        cls.admin.profile.roles.add(cls.admin_role)
        cls.member = User.objects.create_user(username="profile-member", password="testpass123")
        cls.member.profile.first_name = "Philipp"
        cls.member.profile.last_name = "ThÃ¼rlemann"
        cls.member.profile.vulgo = "Newton"
        cls.member.profile.save()

    def test_member_can_edit_own_title_degree_and_birth_date(self):
        self.client.login(username="profile-member", password="testpass123")
        response = self.client.post(
            reverse("profile-edit", kwargs={"pk": self.member.profile.pk}),
            {
                "first_name": "Philipp",
                "last_name": "ThÃ¼rlemann",
                "vulgo": "Newton",
                "academic_title": "MSc",
                "degree_program": "Biotechnology",
                "birth_date": "1998-02-24",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.member.profile.refresh_from_db()
        self.assertEqual(self.member.profile.academic_title, "MSc")
        self.assertEqual(self.member.profile.degree_program, "Biotechnology")
        self.assertEqual(str(self.member.profile.birth_date), "1998-02-24")

    def test_existing_birth_date_is_rendered_in_html5_date_format(self):
        self.member.profile.birth_date = datetime(1998, 2, 24).date()
        self.member.profile.save()

        self.client.login(username="profile-member", password="testpass123")
        response = self.client.get(reverse("profile-edit", kwargs={"pk": self.member.profile.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="1998-02-24"', html=True)

    def test_existing_birth_date_is_not_cleared_when_editing_other_fields(self):
        self.member.profile.birth_date = datetime(1998, 2, 24).date()
        self.member.profile.degree_program = "Biotechnology"
        self.member.profile.save()

        self.client.login(username="profile-member", password="testpass123")
        response = self.client.post(
            reverse("profile-edit", kwargs={"pk": self.member.profile.pk}),
            {
                "first_name": "Philipp",
                "last_name": "ThÃ¼rlemann",
                "vulgo": "Newton",
                "academic_title": "MSc",
                "degree_program": "Humanmedizin",
                "birth_date": "1998-02-24",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.member.profile.refresh_from_db()
        self.assertEqual(self.member.profile.degree_program, "Humanmedizin")
        self.assertEqual(str(self.member.profile.birth_date), "1998-02-24")

    def test_member_cannot_set_entry_exit_or_death_via_manipulated_request(self):
        self.client.login(username="profile-member", password="testpass123")
        self.client.post(
            reverse("profile-edit", kwargs={"pk": self.member.profile.pk}),
            {
                "first_name": "Philipp",
                "last_name": "ThÃ¼rlemann",
                "vulgo": "Newton",
                "academic_title": "MSc",
                "degree_program": "Biotechnology",
                "birth_date": "1998-02-24",
                "entry_year": "2022",
                "entry_semester": "HS",
                "exit_year": "2026",
                "exit_semester": "FS",
                "death_date": "2026-07-17",
            },
            follow=True,
        )
        self.member.profile.refresh_from_db()
        self.assertIsNone(self.member.profile.entry_year)
        self.assertEqual(self.member.profile.entry_semester, "")
        self.assertIsNone(self.member.profile.exit_year)
        self.assertEqual(self.member.profile.exit_semester, "")
        self.assertIsNone(self.member.profile.death_date)

    def test_death_date_not_rendered_in_normal_profile_form(self):
        self.client.login(username="profile-member", password="testpass123")
        response = self.client.get(reverse("profile-edit", kwargs={"pk": self.member.profile.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Todesdatum")

    def test_admin_can_edit_membership_fields_and_death_date(self):
        self.client.login(username="profile-admin", password="testpass123")
        response = self.client.post(
            reverse("profile-edit", kwargs={"pk": self.member.profile.pk}),
            {
                "first_name": "Philipp",
                "last_name": "ThÃ¼rlemann",
                "vulgo": "Newton",
                "academic_title": "Dr. med.",
                "degree_program": "Humanmedizin",
                "birth_date": "1998-02-24",
                "entry_year": "2022",
                "entry_semester": "HS",
                "exit_year": "",
                "exit_semester": "",
                "death_date": "2026-07-17",
                "confirm_death_date_effects": "on",
                "roles": [str(role.pk) for role in self.member.profile.roles.all()],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.member.profile.refresh_from_db()
        self.assertEqual(self.member.profile.entry_year, 2022)
        self.assertEqual(self.member.profile.entry_semester, "HS")
        self.assertEqual(str(self.member.profile.death_date), "2026-07-17")

    def test_setting_death_date_creates_one_memorial_entry_and_disables_login(self):
        self.client.login(username="profile-admin", password="testpass123")
        self.member.profile.academic_title = "Dr. med."
        self.member.profile.birth_date = datetime(1998, 2, 24).date()
        self.member.profile.death_date = datetime(2026, 7, 17).date()
        self.member.profile.save()
        self.member.profile.save()

        entries = MemorialEntry.objects.filter(member_profile=self.member.profile, is_profile_generated=True)
        self.assertEqual(entries.count(), 1)
        entry = entries.get()
        self.assertEqual(entry.display_name, "Dr. med. Philipp ThÃ¼rlemann v/o Newton")
        self.assertEqual(entry.birth_display, "24.02.1998")
        self.assertEqual(entry.death_display, "17.07.2026")
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)

    def test_removing_death_date_unpublishes_generated_memorial_without_reactivating_login(self):
        self.member.profile.death_date = datetime(2026, 7, 17).date()
        self.member.profile.save()
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)

        self.member.profile.death_date = None
        self.member.profile.save()
        entry = MemorialEntry.objects.get(member_profile=self.member.profile, is_profile_generated=True)
        self.assertFalse(entry.is_published)
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)

    def test_name_changes_update_generated_memorial_entry(self):
        self.member.profile.death_date = datetime(2026, 7, 17).date()
        self.member.profile.save()
        self.member.profile.academic_title = "Prof. Dr."
        self.member.profile.vulgo = "Nova"
        self.member.profile.save()
        entry = MemorialEntry.objects.get(member_profile=self.member.profile, is_profile_generated=True)
        self.assertEqual(entry.display_name, "Prof. Dr. Philipp ThÃ¼rlemann v/o Nova")


@skip("The memorial board is internal only; the public endpoint has been removed.")
class MemorialApiTests(TestCase):
    def test_public_memorial_payload_contains_only_allowed_fields_and_is_sorted(self):
        MemorialEntry.objects.create(
            display_name="Historisch Eins",
            death_date_display="April 1990",
            sort_order=5,
            is_published=True,
            legacy_marker="â€ ",
        )
        MemorialEntry.objects.create(
            display_name="Historisch Zwei",
            death_date=datetime(2026, 7, 17).date(),
            is_published=True,
            is_honorary_member=True,
        )
        MemorialEntry.objects.create(
            display_name="Unsichtbar",
            death_date=datetime(2025, 1, 1).date(),
            is_published=False,
        )

        payload = build_public_memorial_payload()

        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["results"][0]["display_name"], "Historisch Zwei")
        self.assertEqual(payload["results"][0]["death_display"], "17.07.2026")
        self.assertEqual(set(payload["results"][0].keys()), {"display_name", "birth_display", "death_display", "is_honorary_member", "legacy_marker"})

    def test_public_memorial_api_excludes_unpublished_entries(self):
        MemorialEntry.objects.create(display_name="Ã–ffentlich", death_date=datetime(2026, 7, 17).date(), is_published=True)
        MemorialEntry.objects.create(display_name="Privat", death_date=datetime(2026, 7, 18).date(), is_published=False)

        response = self.client.get(reverse("api-v1-public-memorials"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["display_name"], "Ã–ffentlich")
class MemorialPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_role = Role.objects.get(code="ADMIN")
        cls.member = User.objects.create_user(username="memorial-member", password="testpass123")
        cls.admin = User.objects.create_user(username="memorial-admin", password="testpass123")
        cls.admin.profile.roles.add(cls.admin_role)

    def test_memorial_page_requires_login(self):
        response = self.client.get(reverse("memorial-page"))
        self.assertEqual(response.status_code, 302)

    def test_logged_in_member_can_view_internal_memorial_page(self):
        MemorialEntry.objects.create(
            display_name="Historisch Zwei",
            death_date=datetime(2026, 7, 17).date(),
            is_published=True,
            is_honorary_member=True,
        )
        MemorialEntry.objects.create(
            display_name="Historisch Kreuz",
            death_date=datetime(2025, 7, 17).date(),
            is_published=True,
            legacy_marker="†",
        )
        MemorialEntry.objects.create(
            display_name="Unsichtbar",
            death_date=datetime(2025, 1, 1).date(),
            is_published=False,
        )

        self.client.login(username="memorial-member", password="testpass123")
        response = self.client.get(reverse("memorial-page"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "avf-memorial-page")
        self.assertContains(response, "avf-memorial-table")
        self.assertContains(response, "avf-memorial-person")
        self.assertContains(response, "Historisch Zwei")
        self.assertContains(response, "Historisch Zwei*")
        self.assertContains(response, "Historisch Kreuz")
        self.assertNotContains(response, "†")
        self.assertNotContains(response, "Unsichtbar")
        self.assertNotContains(response, "/api/v1/public/memorials/")
        self.assertContains(response, "Für immer bleibend")
        self.assertContains(response, "Geboren")
        self.assertContains(response, "Gestorben")
        self.assertNotContains(response, "avf-memorial-actions")

    def test_memorial_page_shows_admin_link_only_for_admins(self):
        entry = MemorialEntry.objects.create(
            display_name="Historisch Eins",
            death_date_display="April 1990",
            is_published=True,
            obituary_document=Document.objects.create(
                title="Nachruf Eins",
                visibility=FolderScope.GENERAL,
                file=SimpleUploadedFile("nachruf.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
                uploaded_by=self.admin,
            ),
        )

        self.client.login(username="memorial-member", password="testpass123")
        member_response = self.client.get(reverse("memorial-page"))
        self.client.logout()

        self.client.login(username="memorial-admin", password="testpass123")
        admin_response = self.client.get(reverse("memorial-page"))

        self.assertNotContains(member_response, reverse("memorial-create"))
        self.assertContains(admin_response, reverse("memorial-create"))
        self.assertContains(admin_response, reverse("memorial-edit", kwargs={"pk": entry.pk}))
        self.assertContains(admin_response, reverse("memorial-delete", kwargs={"pk": entry.pk}))
        self.assertContains(member_response, "Nachruf öffnen")
        self.assertContains(member_response, "Herunterladen")
        self.assertNotContains(member_response, "Bearbeiten")
        self.assertNotContains(member_response, "Löschen")
        self.assertContains(admin_response, "Bearbeiten")
        self.assertContains(admin_response, "Löschen")

    def test_memorial_page_renders_actions_inside_name_cell_without_extra_action_column(self):
        document = Document.objects.create(
            title="Nachruf Struktur",
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile("struktur.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
            uploaded_by=self.admin,
        )
        MemorialEntry.objects.create(
            display_name="Struktur Beispiel",
            death_date=datetime(2026, 7, 17).date(),
            is_published=True,
            obituary_document=document,
        )

        self.client.login(username="memorial-admin", password="testpass123")
        response = self.client.get(reverse("memorial-page"))

        self.assertContains(response, 'class="avf-memorial-person"', html=False)
        self.assertContains(response, 'class="avf-memorial-actions"', html=False)
        self.assertNotContains(response, ">Bearbeiten</th>", html=False)
        self.assertNotContains(response, "avf-memorial-actions\"></span", html=False)

    def test_memorial_form_uses_local_neutral_component_classes(self):
        self.client.login(username="memorial-admin", password="testpass123")

        response = self.client.get(reverse("memorial-create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "avf-memorial-form-page")
        self.assertContains(response, "avf-memorial-form-panel")
        self.assertContains(response, "avf-memorial-submit")

    def test_admin_can_access_internal_memorial_create_and_edit_views_without_django_admin(self):
        entry = MemorialEntry.objects.create(display_name="Historisch Eins", death_date_display="April 1990", is_published=True)

        self.client.login(username="memorial-admin", password="testpass123")
        create_response = self.client.get(reverse("memorial-create"))
        edit_response = self.client.get(reverse("memorial-edit", kwargs={"pk": entry.pk}))

        self.assertEqual(create_response.status_code, 200)
        self.assertEqual(edit_response.status_code, 200)

    def test_admin_can_delete_memorial_entry_from_internal_memorial_page(self):
        entry = MemorialEntry.objects.create(display_name="Zu löschen", death_date_display="April 1990", is_published=True)
        self.client.login(username="memorial-admin", password="testpass123")

        response = self.client.post(reverse("memorial-delete", kwargs={"pk": entry.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(MemorialEntry.objects.filter(pk=entry.pk).exists())

    def test_normal_member_cannot_delete_memorial_entry(self):
        entry = MemorialEntry.objects.create(display_name="Geschützt", death_date_display="April 1990", is_published=True)
        self.client.login(username="memorial-member", password="testpass123")

        response = self.client.post(reverse("memorial-delete", kwargs={"pk": entry.pk}))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(MemorialEntry.objects.filter(pk=entry.pk).exists())

    def test_public_memorial_endpoint_no_longer_exists(self):
        response = self.client.get("/api/v1/public/memorials/")
        self.assertEqual(response.status_code, 404)


class MemorialObituaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_role = Role.objects.get(code="ADMIN")
        cls.admin = User.objects.create_user(username="obituary-admin", password="testpass123")
        cls.admin.profile.roles.add(cls.admin_role)
        cls.member = User.objects.create_user(username="obituary-member", password="testpass123")

    def setUp(self):
        self.temp_media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_media_dir.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.temp_media_dir.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)

    def _pdf_upload(self, name="nachruf.pdf", size=None):
        payload = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
        if size and size > len(payload):
            payload += b"0" * (size - len(payload))
        return SimpleUploadedFile(name, payload, content_type="application/pdf")

    def _create_entry(self, **kwargs):
        defaults = {
            "display_name": "Albert Beispiel",
            "birth_date": datetime(1923, 1, 2).date(),
            "death_date": datetime(1990, 4, 5).date(),
            "is_published": True,
        }
        defaults.update(kwargs)
        return MemorialEntry.objects.create(**defaults)

    def _create_entry_with_obituary(self):
        entry = self._create_entry()
        document = Document.objects.create(
            title="Nachruf Albert Beispiel",
            visibility=FolderScope.GENERAL,
            file=self._pdf_upload(),
            uploaded_by=self.admin,
        )
        entry.obituary_document = document
        entry.save(update_fields=["obituary_document"])
        return entry, document

    def test_memorial_entry_without_obituary_still_works(self):
        entry = self._create_entry()
        self.client.login(username="obituary-member", password="testpass123")

        response = self.client.get(reverse("memorial-page"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, entry.display_name)
        self.assertNotContains(response, "Nachruf öffnen")

    def test_admin_can_upload_pdf(self):
        self.client.login(username="obituary-admin", password="testpass123")

        response = self.client.post(
            reverse("memorial-create"),
            {
                "display_name": "Albert Beispiel",
                "birth_date": "1923-01-02",
                "death_date": "1990-04-05",
                "obituary_upload": self._pdf_upload(),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        entry = MemorialEntry.objects.get(display_name="Albert Beispiel")
        self.assertIsNotNone(entry.obituary_document)
        self.assertEqual(entry.obituary_document.visibility, FolderScope.GENERAL)
        self.assertTrue(entry.obituary_document.file.name.startswith("protected/"))

    def test_normal_member_can_open_pdf(self):
        entry, document = self._create_entry_with_obituary()
        self.client.login(username="obituary-member", password="testpass123")

        preview = self.client.get(reverse("document-preview", kwargs={"pk": document.pk}))
        download = self.client.get(reverse("document-download", kwargs={"pk": document.pk}))
        page = self.client.get(reverse("memorial-page"))

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(download.status_code, 200)
        self.assertContains(page, reverse("document-preview", kwargs={"pk": document.pk}))
        self.assertContains(page, entry.display_name)
        preview.close()
        download.close()

    def test_anonymous_user_cannot_open_pdf(self):
        _entry, document = self._create_entry_with_obituary()

        response = self.client.get(reverse("document-preview", kwargs={"pk": document.pk}))

        self.assertEqual(response.status_code, 302)

    def test_normal_member_cannot_upload_or_replace_pdf(self):
        entry, document = self._create_entry_with_obituary()
        self.client.login(username="obituary-member", password="testpass123")

        create_response = self.client.post(
            reverse("memorial-create"),
            {
                "display_name": "Unerlaubt",
                "death_date": "1990-04-05",
                "obituary_upload": self._pdf_upload("unerlaubt.pdf"),
            },
        )
        edit_response = self.client.post(
            reverse("memorial-edit", kwargs={"pk": entry.pk}),
            {
                "display_name": entry.display_name,
                "birth_date": "1923-01-02",
                "death_date": "1990-04-05",
                "obituary_upload": self._pdf_upload("ersatz.pdf"),
            },
        )

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(edit_response.status_code, 403)
        entry.refresh_from_db()
        self.assertEqual(entry.obituary_document_id, document.pk)

    def test_non_pdf_is_rejected(self):
        self.client.login(username="obituary-admin", password="testpass123")

        response = self.client.post(
            reverse("memorial-create"),
            {
                "display_name": "Falsches Format",
                "death_date": "1990-04-05",
                "obituary_upload": SimpleUploadedFile("nachruf.txt", b"kein pdf", content_type="text/plain"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "obituary_upload",
            "Es sind nur PDF-Dateien mit dem MIME-Type application/pdf erlaubt.",
        )
        self.assertFalse(MemorialEntry.objects.filter(display_name="Falsches Format").exists())

    def test_too_large_pdf_is_rejected(self):
        self.client.login(username="obituary-admin", password="testpass123")

        response = self.client.post(
            reverse("memorial-create"),
            {
                "display_name": "Zu gross",
                "death_date": "1990-04-05",
                "obituary_upload": self._pdf_upload(size=(20 * 1024 * 1024) + 1),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "obituary_upload", "Die PDF-Datei darf höchstens 20 MB gross sein.")

    def test_pdf_can_be_replaced(self):
        entry, old_document = self._create_entry_with_obituary()
        old_file_name = old_document.file.name
        self.client.login(username="obituary-admin", password="testpass123")

        response = self.client.post(
            reverse("memorial-edit", kwargs={"pk": entry.pk}),
            {
                "display_name": entry.display_name,
                "birth_date": "1923-01-02",
                "death_date": "1990-04-05",
                "obituary_upload": self._pdf_upload("neu.pdf"),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        entry.refresh_from_db()
        self.assertIsNotNone(entry.obituary_document)
        self.assertNotEqual(entry.obituary_document_id, old_document.pk)
        self.assertFalse(Document.objects.filter(pk=old_document.pk).exists())
        self.assertFalse(default_storage.exists(old_file_name))

    def test_pdf_can_be_removed(self):
        entry, document = self._create_entry_with_obituary()
        file_name = document.file.name
        self.client.login(username="obituary-admin", password="testpass123")

        response = self.client.post(
            reverse("memorial-edit", kwargs={"pk": entry.pk}),
            {
                "display_name": entry.display_name,
                "birth_date": "1923-01-02",
                "death_date": "1990-04-05",
                "obituary_remove": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        entry.refresh_from_db()
        self.assertIsNone(entry.obituary_document)
        self.assertTrue(MemorialEntry.objects.filter(pk=entry.pk).exists())
        self.assertFalse(Document.objects.filter(pk=document.pk).exists())
        self.assertFalse(default_storage.exists(file_name))

    def test_automatic_profile_update_keeps_pdf_link(self):
        profile = self.member.profile
        profile.first_name = "Albert"
        profile.last_name = "Beispiel"
        profile.birth_date = datetime(1923, 1, 2).date()
        profile.death_date = datetime(1990, 4, 5).date()
        profile.save()
        entry = MemorialEntry.objects.get(member_profile=profile, is_profile_generated=True)
        document = Document.objects.create(
            title="Nachruf Albert Beispiel",
            visibility=FolderScope.GENERAL,
            file=self._pdf_upload(),
            uploaded_by=self.admin,
        )
        entry.obituary_document = document
        entry.save(update_fields=["obituary_document"])

        profile.academic_title = "Dr."
        profile.save()

        entry.refresh_from_db()
        self.assertEqual(entry.obituary_document_id, document.pk)

    def test_removing_obituary_does_not_delete_memorial_entry(self):
        entry, _document = self._create_entry_with_obituary()
        self.client.login(username="obituary-admin", password="testpass123")

        self.client.post(
            reverse("memorial-edit", kwargs={"pk": entry.pk}),
            {
                "display_name": entry.display_name,
                "birth_date": "1923-01-02",
                "death_date": "1990-04-05",
                "obituary_remove": "on",
            },
            follow=True,
        )

        self.assertTrue(MemorialEntry.objects.filter(pk=entry.pk).exists())

    def test_deleting_memorial_entry_also_removes_linked_obituary_document(self):
        entry, document = self._create_entry_with_obituary()
        file_name = document.file.name
        self.client.login(username="obituary-admin", password="testpass123")

        response = self.client.post(reverse("memorial-delete", kwargs={"pk": entry.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(MemorialEntry.objects.filter(pk=entry.pk).exists())
        self.assertFalse(Document.objects.filter(pk=document.pk).exists())
        self.assertFalse(default_storage.exists(file_name))

    def test_direct_public_file_address_is_not_usable(self):
        _entry, document = self._create_entry_with_obituary()

        response = self.client.get(document.file.url)

        self.assertNotEqual(response.status_code, 200)


class MemorialImportCommandTests(TestCase):
    def test_import_command_is_idempotent_via_import_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "memorial.csv"
            csv_path.write_text(
                dedent(
                    """\
                    import_key,display_name,birth_date,birth_date_display,death_date,death_date_display,is_honorary_member,legacy_marker,sort_order,is_published
                    hist-1,Historisch Eins,1923-01-02,,1990-04-05,,0,â€ ,5,1
                    """
                ),
                encoding="utf-8",
            )

            call_command("import_memorial_entries", str(csv_path))
            call_command("import_memorial_entries", str(csv_path))

        self.assertEqual(MemorialEntry.objects.count(), 1)
        entry = MemorialEntry.objects.get()
        self.assertEqual(entry.import_key, "hist-1")
        self.assertEqual(entry.display_name, "Historisch Eins")
        self.assertEqual(entry.death_display, "05.04.1990")
        self.assertEqual(entry.legacy_marker, "")

    def test_import_command_keeps_unknown_day_month_as_display_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "memorial.csv"
            csv_path.write_text(
                dedent(
                    """\
                    import_key,display_name,birth_date,birth_date_display,death_date,death_date_display,is_honorary_member,legacy_marker,sort_order,is_published
                    hist-2,Historisch Zwei,,00.00.1923,,,0,,0,1
                    """
                ),
                encoding="utf-8",
            )

            call_command("import_memorial_entries", str(csv_path))

        entry = MemorialEntry.objects.get(import_key="hist-2")
        self.assertIsNone(entry.birth_date)
        self.assertEqual(entry.birth_date_display, "1923")

    def test_import_command_dry_run_does_not_persist_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "memorial.csv"
            csv_path.write_text(
                dedent(
                    """\
                    import_key,display_name,birth_date,birth_date_display,death_date,death_date_display,is_honorary_member,legacy_marker,sort_order,is_published
                    hist-3,Historisch Drei,,,,,0,,0,1
                    """
                ),
                encoding="utf-8",
            )

            call_command("import_memorial_entries", str(csv_path), dry_run=True)

        self.assertFalse(MemorialEntry.objects.filter(import_key="hist-3").exists())

    def test_import_command_without_import_key_does_not_merge_equal_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "memorial.csv"
            csv_path.write_text(
                dedent(
                    """\
                    display_name,birth_date,birth_date_display,death_date,death_date_display,is_honorary_member,legacy_marker,sort_order,is_published
                    Historisch Gleich,,,,,0,,0,1
                    Historisch Gleich,,1924,,,,0,,1,1
                    """
                ),
                encoding="utf-8",
            )

            call_command("import_memorial_entries", str(csv_path))

        self.assertEqual(MemorialEntry.objects.filter(display_name="Historisch Gleich").count(), 2)

    def test_import_command_updates_generated_entry_without_losing_pdf_or_profile_link(self):
        admin = User.objects.create_user(username="import-admin", password="testpass123")
        user = User.objects.create_user(username="import-profile", password="testpass123")
        profile = user.profile
        profile.first_name = "Albert"
        profile.last_name = "Beispiel"
        profile.vulgo = "Noel"
        profile.death_date = datetime(1997, 8, 1).date()
        profile.save()
        entry = MemorialEntry.objects.get(member_profile=profile, is_profile_generated=True)
        document = Document.objects.create(
            title="Nachruf Albert Beispiel",
            visibility=FolderScope.GENERAL,
            file=SimpleUploadedFile("nachruf.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"),
            uploaded_by=admin,
        )
        entry.obituary_document = document
        entry.save(update_fields=["obituary_document"])

        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "memorial.csv"
            csv_path.write_text(
                dedent(
                    """\
                    display_name,birth_date,birth_date_display,death_date,death_date_display,is_honorary_member,legacy_marker,sort_order,is_published
                    Albert Beispiel v/o Noel,,,1997-08-01,,0,,83,1
                    """
                ),
                encoding="utf-8",
            )

            call_command("import_memorial_entries", str(csv_path))

        entry.refresh_from_db()
        self.assertEqual(entry.member_profile_id, profile.pk)
        self.assertTrue(entry.is_profile_generated)
        self.assertEqual(entry.obituary_document_id, document.pk)
        self.assertEqual(entry.sort_order, 83)
        self.assertTrue(entry.is_published)
        self.assertEqual(entry.legacy_marker, "")

    def test_import_command_ignores_dagger_legacy_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "memorial.csv"
            csv_path.write_text(
                dedent(
                    """\
                    display_name,birth_date,birth_date_display,death_date,death_date_display,is_honorary_member,legacy_marker,sort_order,is_published
                    Historisch Kreuz,,1923,1990-04-05,,0,†,1,1
                    """
                ),
                encoding="utf-8",
            )

            call_command("import_memorial_entries", str(csv_path))

        entry = MemorialEntry.objects.get(display_name="Historisch Kreuz")
        self.assertEqual(entry.legacy_marker, "")


class BootstrapInternalCommandTests(TestCase):
    """SEC-014: the initial-admin password must never be accepted as a CLI
    argument (visible in `ps aux` / shell history) - only via an environment
    variable (scripted/non-interactive) or an interactive, non-echoing prompt."""

    def test_password_cli_flag_no_longer_exists(self):
        with self.assertRaises(CommandError):
            call_command("bootstrap_internal", "--username", "shouldfail", "--password", "leaked-on-cli")

    def test_password_from_environment_variable_is_used(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"AVF_BOOTSTRAP_ADMIN_PASSWORD": "from-env-Secure123!"}):
            call_command("bootstrap_internal", "--username", "env-admin", "--email", "env-admin@example.org")

        user = User.objects.get(username="env-admin")
        self.assertTrue(user.check_password("from-env-Secure123!"))
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_password_prompted_interactively_when_env_var_missing(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AVF_BOOTSTRAP_ADMIN_PASSWORD", None)
            with patch("getpass.getpass", return_value="prompted-Secure123!") as mocked_prompt:
                call_command("bootstrap_internal", "--username", "prompt-admin")
            mocked_prompt.assert_called_once()

        user = User.objects.get(username="prompt-admin")
        self.assertTrue(user.check_password("prompted-Secure123!"))

    def test_empty_password_everywhere_aborts_without_creating_a_user(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AVF_BOOTSTRAP_ADMIN_PASSWORD", None)
            with patch("getpass.getpass", return_value=""):
                with self.assertRaises(SystemExit):
                    call_command("bootstrap_internal", "--username", "nopassword-admin")

        self.assertFalse(User.objects.filter(username="nopassword-admin").exists())

