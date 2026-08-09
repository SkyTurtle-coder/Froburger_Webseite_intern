from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Role


class NavigationAndUiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_role = Role.objects.get(code="ADMIN")
        cls.webx_role = Role.objects.get(code="WEB_X")

        cls.member = User.objects.create_user(username="member-ui", password="testpass123")
        cls.member.profile.first_name = "Philipp"
        cls.member.profile.last_name = "Thuerlemann"
        cls.member.profile.vulgo = "Newton"
        cls.member.profile.save()

        cls.admin = User.objects.create_user(username="admin-ui", password="testpass123")
        cls.admin.profile.first_name = "Ada"
        cls.admin.profile.last_name = "Admin"
        cls.admin.profile.roles.add(cls.admin_role)
        cls.admin.profile.save()

        cls.webx = User.objects.create_user(username="webx-ui", password="testpass123")
        cls.webx.profile.first_name = "Wera"
        cls.webx.profile.last_name = "Web"
        cls.webx.profile.roles.add(cls.webx_role)
        cls.webx.profile.save()

        cls.profile_a = User.objects.create_user(username="alpha", password="testpass123")
        cls.profile_a.profile.first_name = "Anna"
        cls.profile_a.profile.last_name = "Aebi"
        cls.profile_a.profile.vulgo = "Zeta"
        cls.profile_a.profile.save()

        cls.profile_b = User.objects.create_user(username="beta", password="testpass123")
        cls.profile_b.profile.first_name = "Berta"
        cls.profile_b.profile.last_name = "Mueller"
        cls.profile_b.profile.vulgo = "Alpha"
        cls.profile_b.profile.save()

        cls.profile_c = User.objects.create_user(username="gamma", password="testpass123")
        cls.profile_c.profile.first_name = "Clara"
        cls.profile_c.profile.last_name = "Oeri"
        cls.profile_c.profile.vulgo = ""
        cls.profile_c.profile.save()

    def setUp(self):
        cache.clear()

    @override_settings(
        PUBLIC_WEBSITE_PRIMARY_URL="https://test.avfroburger.ch/",
        PUBLIC_WEBSITE_FALLBACK_URL="https://avfroburger.ch/",
    )
    @patch("core.public_site.urlopen")
    def test_dashboard_uses_primary_public_site_url_when_reachable(self, mock_urlopen):
        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.status = 200
        mock_response.geturl.return_value = "https://test.avfroburger.ch/"
        self.client.login(username="member-ui", password="testpass123")

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="https://test.avfroburger.ch/"')
        self.assertContains(response, 'data-menu-toggle')
        self.assertContains(response, 'data-nav-overlay')
        self.assertNotContains(response, "mobile-nav__summary")

    @override_settings(
        PUBLIC_WEBSITE_PRIMARY_URL="https://test.avfroburger.ch/",
        PUBLIC_WEBSITE_FALLBACK_URL="https://avfroburger.ch/",
    )
    @patch("core.public_site.urlopen", side_effect=TimeoutError)
    def test_dashboard_falls_back_to_public_site_when_primary_times_out(self, _mock_urlopen):
        self.client.login(username="member-ui", password="testpass123")

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="https://avfroburger.ch/"')

    @override_settings(
        PUBLIC_WEBSITE_PRIMARY_URL="https://test.avfroburger.ch/",
        PUBLIC_WEBSITE_FALLBACK_URL="https://avfroburger.ch/",
    )
    @patch("core.public_site.urlopen")
    def test_login_page_uses_exact_primary_public_url(self, mock_urlopen):
        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.status = 200
        mock_response.geturl.return_value = "https://test.avfroburger.ch/"

        response = self.client.get(reverse("login"))

        self.assertContains(response, 'href="https://test.avfroburger.ch/"')

    @override_settings(
        PUBLIC_WEBSITE_PRIMARY_URL="https://test.avfroburger.ch/",
        PUBLIC_WEBSITE_FALLBACK_URL="https://avfroburger.ch/",
    )
    @patch("core.public_site.urlopen")
    def test_dashboard_sidebar_groups_navigation_below_dashboard(self, mock_urlopen):
        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.status = 200
        mock_response.geturl.return_value = "https://test.avfroburger.ch/"
        self.client.login(username="member-ui", password="testpass123")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, '<a href="/" class="nav__item nav__item--active">Dashboard</a>', html=False)
        self.assertContains(response, '<details class="nav__disclosure"', html=False)
        rendered = response.content.decode()
        self.assertLess(rendered.index("Dashboard</a>"), rendered.index('<details class="nav__disclosure"'))
        self.assertIn("Zur Webseite", rendered)
        self.assertNotIn("mobile-nav", rendered)

    @override_settings(
        PUBLIC_WEBSITE_PRIMARY_URL="https://test.avfroburger.ch/",
        PUBLIC_WEBSITE_FALLBACK_URL="https://avfroburger.ch/",
    )
    @patch("core.public_site.urlopen")
    def test_member_directory_marks_navigation_open_and_active(self, mock_urlopen):
        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.status = 200
        mock_response.geturl.return_value = "https://test.avfroburger.ch/"
        self.client.login(username="member-ui", password="testpass123")

        response = self.client.get(reverse("member-directory"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<details class="nav__disclosure" open>', html=False)
        self.assertContains(response, 'class="nav__item nav__item--subtle nav__item--active">Mitglieder</a>', html=False)

    @override_settings(
        PUBLIC_WEBSITE_PRIMARY_URL="https://test.avfroburger.ch/",
        PUBLIC_WEBSITE_FALLBACK_URL="https://avfroburger.ch/",
    )
    @patch("core.public_site.urlopen")
    def test_event_list_marks_navigation_open(self, mock_urlopen):
        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.status = 200
        mock_response.geturl.return_value = "https://test.avfroburger.ch/"
        self.client.login(username="webx-ui", password="testpass123")

        response = self.client.get(reverse("event-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<details class="nav__disclosure" open>', html=False)
        self.assertContains(response, "Anlässe")

    @override_settings(
        PUBLIC_WEBSITE_PRIMARY_URL="https://test.avfroburger.ch/",
        PUBLIC_WEBSITE_FALLBACK_URL="https://avfroburger.ch/",
    )
    @patch("core.public_site.urlopen")
    def test_dashboard_keeps_navigation_disclosure_closed_by_default(self, mock_urlopen):
        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.status = 200
        mock_response.geturl.return_value = "https://test.avfroburger.ch/"
        self.client.login(username="member-ui", password="testpass123")

        response = self.client.get(reverse("dashboard"))

        rendered = response.content.decode()
        self.assertIn('<details class="nav__disclosure" >', rendered)
        self.assertNotIn('<details class="nav__disclosure" open>', rendered)

    @override_settings(
        PUBLIC_WEBSITE_PRIMARY_URL="https://test.avfroburger.ch/",
        PUBLIC_WEBSITE_FALLBACK_URL="https://avfroburger.ch/",
    )
    @patch("core.public_site.urlopen")
    def test_administration_link_remains_permission_bound(self, mock_urlopen):
        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.status = 200
        mock_response.geturl.return_value = "https://test.avfroburger.ch/"

        self.client.login(username="member-ui", password="testpass123")
        member_response = self.client.get(reverse("dashboard"))
        self.client.logout()

        self.client.login(username="admin-ui", password="testpass123")
        admin_response = self.client.get(reverse("dashboard"))

        self.assertNotContains(member_response, "Administration")
        self.assertContains(admin_response, "Administration")

    def test_member_directory_defaults_to_name_ascending_and_vo_heading(self):
        self.client.login(username="member-ui", password="testpass123")

        response = self.client.get(reverse("member-directory"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ">v/o<", html=False)
        self.assertContains(response, 'aria-sort="ascending"', count=1)
        rendered = response.content.decode()
        self.assertLess(rendered.index("Aebi"), rendered.index("Mueller"))
        self.assertLess(rendered.index("Mueller"), rendered.index("Oeri"))

    def test_member_directory_supports_vulgo_descending(self):
        self.client.login(username="member-ui", password="testpass123")

        response = self.client.get(reverse("member-directory"), {"sort": "vulgo", "direction": "desc"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '?sort=vulgo&direction=asc', html=False)
        rendered = response.content.decode()
        self.assertLess(rendered.index("Zeta"), rendered.index("Alpha"))

    def test_invalid_member_directory_sort_parameters_fall_back_safely(self):
        self.client.login(username="member-ui", password="testpass123")

        response = self.client.get(reverse("member-directory"), {"sort": "email", "direction": "sideways"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="sort" value="name"', html=False)
        self.assertContains(response, 'name="direction" value="asc"', html=False)

    def test_document_hub_no_longer_renders_intro_card_copy(self):
        self.client.login(username="member-ui", password="testpass123")

        response = self.client.get(reverse("document-hub"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Dokumentenverwaltung")
        self.assertNotContains(response, "zwei Schutzstufen")

    def test_profile_edit_renders_responsive_form_structure(self):
        self.client.login(username="member-ui", password="testpass123")

        response = self.client.get(reverse("profile-edit", kwargs={"pk": self.member.profile.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "profile-form__grid")
        self.assertContains(response, "Speichern")
        self.assertNotContains(response, "Zum Inhalt")

    @override_settings(
        PUBLIC_WEBSITE_PRIMARY_URL="https://test.avfroburger.ch/",
        PUBLIC_WEBSITE_FALLBACK_URL="https://avfroburger.ch/",
    )
    @patch("core.public_site.urlopen")
    def test_dashboard_shows_personal_profile_overview_for_regular_member(self, mock_urlopen):
        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.status = 200
        mock_response.geturl.return_value = "https://test.avfroburger.ch/"
        self.member.profile.academic_title = "MSc"
        self.member.profile.degree_program = "Biotechnology"
        self.member.profile.entry_year = 2022
        self.member.profile.entry_semester = "HS"
        self.member.profile.save()
        self.client.login(username="member-ui", password="testpass123")

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Biotechnology")
        self.assertContains(response, "MSc")
        self.assertContains(response, "2022 HS")
        self.assertContains(response, "v/o Newton")
        self.assertNotContains(response, "Mitgliederprofile")

    @override_settings(
        PUBLIC_WEBSITE_PRIMARY_URL="https://test.avfroburger.ch/",
        PUBLIC_WEBSITE_FALLBACK_URL="https://avfroburger.ch/",
    )
    @patch("core.public_site.urlopen")
    def test_admin_dashboard_still_shows_compact_metrics(self, mock_urlopen):
        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.status = 200
        mock_response.geturl.return_value = "https://test.avfroburger.ch/"
        self.client.login(username="admin-ui", password="testpass123")

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mitgliederprofile")
        self.assertContains(response, "Sensible Dokumente")
        self.assertContains(response, "Systemübersicht")
