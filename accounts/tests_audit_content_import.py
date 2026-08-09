import hashlib
import io
import json
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command, CommandError
from django.test import TestCase
from django.test.utils import override_settings

from accounts.management.commands.audit_content_import import (
    build_role_mapping_payload,
    rewrite_fixture_for_seeded_roles,
)
from accounts.models import Role
from events.models import Event


class AuditContentImportCommandTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.media_root = Path(self.temp_dir.name) / "media"
        self.media_root.mkdir(parents=True, exist_ok=True)

    def write_fixture(self, payload, name="fixture.json"):
        path = Path(self.temp_dir.name) / name
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def write_manifest(self, payload, name="manifest.json"):
        path = Path(self.temp_dir.name) / name
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def run_command(self, fixture_path, **kwargs):
        stdout = io.StringIO()
        stderr = io.StringIO()
        call_command(
            "audit_content_import",
            str(fixture_path),
            media_root=str(self.media_root),
            stdout=stdout,
            stderr=stderr,
            **kwargs,
        )
        return stdout.getvalue(), stderr.getvalue()

    def run_prepare_command(self, source_fixture, source_manifest, **kwargs):
        stdout = io.StringIO()
        stderr = io.StringIO()
        target_fixture = Path(self.temp_dir.name) / "target.json"
        role_mapping = Path(self.temp_dir.name) / "role-mapping.json"
        target_manifest = Path(self.temp_dir.name) / "manifest-target.json"
        call_command(
            "prepare_content_import",
            str(source_fixture),
            source_manifest=str(source_manifest),
            output_fixture=str(target_fixture),
            output_role_mapping=str(role_mapping),
            output_manifest=str(target_manifest),
            media_root=str(self.media_root),
            stdout=stdout,
            stderr=stderr,
            **kwargs,
        )
        return {
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "target_fixture": target_fixture,
            "role_mapping": role_mapping,
            "target_manifest": target_manifest,
        }

    def make_user_fixture(self, pk=101, **field_overrides):
        fields = {
            "password": "pbkdf2_sha256$1000000$testsalt$testhash",
            "last_login": None,
            "is_superuser": False,
            "username": f"fixture-user-{pk}",
            "first_name": "Test",
            "last_name": f"User{pk}",
            "email": f"fixture{pk}@example.test",
            "is_staff": False,
            "is_active": True,
            "date_joined": "2026-08-04T09:00:00Z",
            "groups": [],
            "user_permissions": [],
        }
        fields.update(field_overrides)
        return {"model": "auth.user", "pk": pk, "fields": fields}

    def make_role_fixture(self, pk, code):
        return {"model": "accounts.role", "pk": pk, "fields": {"code": code}}

    def make_profile_fixture(self, pk=201, user_id=101, role_ids=None, photo="", **field_overrides):
        if role_ids is None:
            role_ids = []
        fields = {
            "user": user_id,
            "photo": photo,
            "first_name": "Profile",
            "last_name": f"Fixture{pk}",
            "vulgo": "",
            "roles": role_ids,
        }
        fields.update(field_overrides)
        return {"model": "accounts.profile", "pk": pk, "fields": fields}

    def make_event_fixture(self, pk, slug=None):
        slug = slug or f"fixture-event-{pk}"
        return {
            "model": "events.event",
            "pk": pk,
            "fields": {
                "title": f"Fixture Event {pk}",
                "slug": slug,
                "short_description": f"Short {pk}",
                "description": f"Description {pk}",
                "start": "2026-08-12T18:00:00Z",
                "end": "2026-08-12T20:00:00Z",
                "location": "Basel",
                "status": "OFF",
                "is_public": True,
                "show_on_homepage": True,
                "signup_enabled": True,
                "created_at": "2026-08-04T09:00:00Z",
                "updated_at": "2026-08-04T09:00:00Z",
            },
        }

    def build_role_fixture_entries(self, pk_transform=None):
        entries = []
        for role in Role.objects.order_by("code"):
            source_pk = pk_transform(role.pk) if pk_transform else role.pk
            entries.append(self.make_role_fixture(pk=source_pk, code=role.code))
        return entries

    def build_full_source_fixture(self, pk_transform=None):
        role_entries = self.build_role_fixture_entries(pk_transform=pk_transform)
        role_pk_by_code = {entry["fields"]["code"]: entry["pk"] for entry in role_entries}
        all_role_codes = list(role_pk_by_code.keys())
        public_codes = [code for code in all_role_codes if code != "ADMIN"]

        users = []
        profiles = []
        for index in range(22):
            user_pk = 1001 + index
            profile_pk = 2001 + index
            users.append(
                self.make_user_fixture(
                    pk=user_pk,
                    username=f"source-user-{index}",
                    email=f"source-user-{index}@example.test",
                    is_staff=index == 0,
                    is_superuser=index == 0,
                )
            )
            role_codes = [public_codes[index % len(public_codes)]]
            if index == 0:
                role_codes.append("ADMIN")
            profiles.append(
                self.make_profile_fixture(
                    pk=profile_pk,
                    user_id=user_pk,
                    role_ids=[role_pk_by_code[code] for code in role_codes],
                    first_name="Fixture",
                    last_name=f"Profile{index:02d}",
                )
            )

        events = [self.make_event_fixture(pk=3001 + index) for index in range(6)]
        payload = users + role_entries + profiles + events
        self.assertEqual(Counter(item["model"] for item in payload)["auth.user"], 22)
        self.assertEqual(Counter(item["model"] for item in payload)["accounts.role"], 13)
        self.assertEqual(Counter(item["model"] for item in payload)["accounts.profile"], 22)
        self.assertEqual(Counter(item["model"] for item in payload)["events.event"], 6)
        self.assertEqual(len(payload), 63)
        return payload

    def source_manifest_payload(self, fixture_path, fixture_payload):
        return {
            "created_at": "2026-08-04T12:03:52+02:00",
            "source_database_path": str(Path(self.temp_dir.name) / "db.sqlite3.analysis-copy"),
            "source_database_size": 233472,
            "fixture_filename": fixture_path.name,
            "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
            "object_counts": dict(sorted(Counter(item["model"] for item in fixture_payload).items())),
            "allowed_model_labels": [
                "accounts.profile",
                "accounts.role",
                "auth.user",
                "events.event",
                "events.eventsignup",
                "events.eventsignupcolumn",
            ],
            "excluded_models": [
                "auth.group",
                "auth.permission",
                "documents.document",
            ],
            "media_files": [],
            "django_version": "5.2.16",
            "python_version": "3.12.7",
            "applied_migrations": 27,
            "worktree_status": "git-unavailable",
        }

    def test_valid_minimal_fixture_passes(self):
        fixture = self.write_fixture([self.make_user_fixture(pk=901)])
        stdout, _ = self.run_command(fixture)
        self.assertIn("AUDIT RESULT: PASS", stdout)

    def test_unknown_model_is_rejected(self):
        fixture = self.write_fixture([{"model": "unknown.model", "pk": 1, "fields": {}}])
        with self.assertRaises(CommandError):
            self.run_command(fixture)

    def test_not_allowed_model_is_rejected(self):
        fixture = self.write_fixture([{"model": "documents.document", "pk": 1, "fields": {}}])
        with self.assertRaises(CommandError):
            self.run_command(fixture)

    def test_duplicate_pk_is_detected(self):
        fixture = self.write_fixture([self.make_user_fixture(pk=901), self.make_user_fixture(pk=901)])
        with self.assertRaises(CommandError):
            self.run_command(fixture)

    def test_pk_conflict_with_target_db_is_detected(self):
        User.objects.create_user(username="existing-user", password="testpass123")
        fixture = self.write_fixture([self.make_user_fixture(pk=1)])
        with self.assertRaises(CommandError):
            self.run_command(fixture)

    def test_missing_user_for_profile_is_detected(self):
        fixture = self.write_fixture([self.make_profile_fixture(user_id=9999)])
        with self.assertRaises(CommandError):
            self.run_command(fixture)

    def test_missing_role_in_profile_roles_is_detected(self):
        fixture = self.write_fixture(
            [
                self.make_user_fixture(pk=901),
                self.make_profile_fixture(pk=902, user_id=901, role_ids=[9999]),
            ]
        )
        with self.assertRaises(CommandError):
            self.run_command(fixture)

    def test_onetoone_conflict_is_detected(self):
        user = User.objects.create_user(username="existing-o2o", password="testpass123")
        fixture = self.write_fixture([self.make_profile_fixture(pk=999, user_id=user.pk)])
        with self.assertRaises(CommandError):
            self.run_command(fixture)

    def test_unique_conflict_is_detected(self):
        Event.objects.create(
            title="Existing Event",
            slug="same-slug",
            short_description="Existing",
            description="Existing event",
            start="2026-08-10T18:00:00Z",
            end="2026-08-10T20:00:00Z",
            location="Basel",
            status="OFF",
            is_public=True,
            show_on_homepage=True,
        )
        fixture = self.write_fixture([self.make_event_fixture(pk=900, slug="same-slug")])
        with self.assertRaises(CommandError):
            self.run_command(fixture)

    def test_absolute_media_path_is_rejected(self):
        fixture = self.write_fixture(
            [
                self.make_user_fixture(pk=901),
                self.make_profile_fixture(pk=902, user_id=901, photo="C:\\secret\\photo.jpg"),
            ]
        )
        with self.assertRaises(CommandError):
            self.run_command(fixture)

    def test_traversal_media_path_is_rejected(self):
        fixture = self.write_fixture(
            [
                self.make_user_fixture(pk=901),
                self.make_profile_fixture(pk=902, user_id=901, photo="../secret/photo.jpg"),
            ]
        )
        with self.assertRaises(CommandError):
            self.run_command(fixture)

    def test_missing_media_file_is_detected(self):
        fixture = self.write_fixture(
            [
                self.make_user_fixture(pk=901),
                self.make_profile_fixture(pk=902, user_id=901, photo="avatars/missing.jpg"),
            ]
        )
        with self.assertRaises(CommandError):
            self.run_command(fixture)

    def test_valid_relative_media_path_passes(self):
        photo_path = self.media_root / "avatars" / "ok.jpg"
        photo_path.parent.mkdir(parents=True, exist_ok=True)
        photo_path.write_bytes(b"jpeg-bytes")
        fixture = self.write_fixture(
            [
                self.make_user_fixture(pk=901),
                self.make_profile_fixture(pk=902, user_id=901, photo="avatars/ok.jpg"),
            ]
        )
        stdout, _ = self.run_command(fixture)
        self.assertIn("AUDIT RESULT: PASS", stdout)

    def test_command_does_not_modify_database(self):
        before = (User.objects.count(), Event.objects.count())
        fixture = self.write_fixture([self.make_user_fixture(pk=901)])
        self.run_command(fixture)
        after = (User.objects.count(), Event.objects.count())
        self.assertEqual(before, after)

    def test_sensitive_fields_do_not_appear_in_output(self):
        fixture = self.write_fixture([self.make_user_fixture(pk=901, username="secret-user", email="secret@example.test")])
        stdout, stderr = self.run_command(fixture)
        self.assertNotIn("secret-user", stdout + stderr)
        self.assertNotIn("secret@example.test", stdout + stderr)

    def test_fixture_not_readable_exits_with_code_2(self):
        with self.assertRaises(SystemExit) as exc:
            self.run_command(Path(self.temp_dir.name) / "missing.json")
        self.assertEqual(exc.exception.code, 2)

    @override_settings(MEDIA_ROOT="/tmp/audit-import-test")
    def test_json_output_contains_summary_only(self):
        fixture = self.write_fixture([self.make_user_fixture(pk=901)])
        stdout = io.StringIO()
        call_command(
            "audit_content_import",
            str(fixture),
            media_root=str(self.media_root),
            json=True,
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["result"], "PASS")
        self.assertEqual(payload["model_counts"]["auth.user"], 1)

    def test_seed_match_with_identical_role_pks_passes(self):
        fixture = self.write_fixture(self.build_role_fixture_entries(), name="roles-identical.json")
        stdout, _ = self.run_command(fixture, role_strategy="seed-match")
        self.assertIn("AUDIT RESULT: PASS", stdout)
        self.assertIn("Role strategy: seed-match", stdout)
        self.assertIn("Role ROLE_PK_MATCH", stdout)

    def test_seed_match_with_different_role_pks_reports_remap(self):
        payload = self.build_role_fixture_entries(pk_transform=lambda pk: pk + 1000)
        fixture = self.write_fixture(payload, name="roles-remap.json")
        stdout, _ = self.run_command(fixture, role_strategy="seed-match")
        self.assertIn("AUDIT RESULT: PASS", stdout)
        self.assertIn("ROLE_PK_REMAP_REQUIRED", stdout)

    def test_seed_match_missing_target_role_fails(self):
        payload = [self.make_role_fixture(pk=9999, code="MISSING_ROLE")]
        fixture = self.write_fixture(payload, name="roles-missing.json")
        with self.assertRaises(CommandError):
            self.run_command(fixture, role_strategy="seed-match")

    def test_seed_match_extra_target_role_fails_by_default(self):
        Role.objects.create(code="EXTRA_ROLE")
        fixture = self.write_fixture(
            [self.make_role_fixture(pk=role.pk, code=role.code) for role in Role.objects.exclude(code="EXTRA_ROLE").order_by("code")],
            name="roles-extra-target.json",
        )
        with self.assertRaises(CommandError):
            self.run_command(fixture, role_strategy="seed-match")

    def test_seed_match_duplicate_business_key_fails(self):
        payload = [
            self.make_role_fixture(pk=5001, code="ADMIN"),
            self.make_role_fixture(pk=5002, code="ADMIN"),
        ]
        fixture = self.write_fixture(payload, name="roles-duplicate-key.json")
        with self.assertRaises(CommandError):
            self.run_command(fixture, role_strategy="seed-match")

    def test_seed_match_profile_unknown_role_fails(self):
        fixture = self.write_fixture(
            [
                self.make_user_fixture(pk=901),
                self.make_profile_fixture(pk=902, user_id=901, role_ids=[9999]),
            ],
            name="profile-role-unknown.json",
        )
        with self.assertRaises(CommandError):
            self.run_command(fixture, role_strategy="seed-match")

    def test_seed_match_profile_roles_can_be_mapped(self):
        source_roles = self.build_role_fixture_entries(pk_transform=lambda pk: pk + 1000)
        role_pk_by_code = {entry["fields"]["code"]: entry["pk"] for entry in source_roles}
        fixture = self.write_fixture(
            [
                self.make_user_fixture(pk=901),
                *source_roles,
                self.make_profile_fixture(pk=902, user_id=901, role_ids=[role_pk_by_code["ADMIN"]]),
            ],
            name="profile-role-known.json",
        )
        stdout, _ = self.run_command(fixture, role_strategy="seed-match")
        self.assertIn("AUDIT RESULT: PASS", stdout)

    def test_target_seeded_fixture_rejects_role_objects(self):
        fixture = self.write_fixture(self.build_role_fixture_entries(), name="target-seeded-roles.json")
        with self.assertRaises(CommandError):
            self.run_command(fixture, role_strategy="target-seeded")

    def test_rewrite_fixture_drops_roles_and_preserves_other_models(self):
        source = self.build_full_source_fixture(pk_transform=lambda pk: pk + 1000)
        source_copy = deepcopy(source)
        role_entries = [item for item in source if item["model"] == "accounts.role"]
        mapping = {}
        for entry in role_entries:
            target_role = Role.objects.get(code=entry["fields"]["code"])
            mapping[entry["pk"]] = {
                "target_pk": target_role.pk,
                "status": "ROLE_PK_REMAP_REQUIRED",
                "role_key": entry["fields"]["code"],
                "compared_fields": {"code": entry["fields"]["code"]},
                "field_hash": "hash",
            }
        rewritten = rewrite_fixture_for_seeded_roles(source, mapping)
        self.assertEqual(source, source_copy)
        counts = Counter(item["model"] for item in rewritten)
        self.assertNotIn("accounts.role", counts)
        self.assertEqual(counts["auth.user"], 22)
        self.assertEqual(counts["accounts.profile"], 22)
        self.assertEqual(counts["events.event"], 6)
        self.assertEqual(len(rewritten), 50)

    def test_rewrite_keeps_profile_roles_when_pks_match(self):
        source = self.build_full_source_fixture()
        role_entries = [item for item in source if item["model"] == "accounts.role"]
        mapping = {}
        for entry in role_entries:
            mapping[entry["pk"]] = {
                "target_pk": entry["pk"],
                "status": "ROLE_PK_MATCH",
                "role_key": entry["fields"]["code"],
                "compared_fields": {"code": entry["fields"]["code"]},
                "field_hash": "hash",
            }
        original_profile_roles = {
            item["pk"]: list(item["fields"]["roles"])
            for item in source
            if item["model"] == "accounts.profile"
        }
        rewritten = rewrite_fixture_for_seeded_roles(source, mapping)
        rewritten_profile_roles = {
            item["pk"]: list(item["fields"]["roles"])
            for item in rewritten
            if item["model"] == "accounts.profile"
        }
        self.assertEqual(original_profile_roles, rewritten_profile_roles)

    def test_rewrite_only_changes_profile_roles_when_pks_differ(self):
        source = self.build_full_source_fixture(pk_transform=lambda pk: pk + 1000)
        source_profiles = {
            item["pk"]: deepcopy(item["fields"])
            for item in source
            if item["model"] == "accounts.profile"
        }
        role_entries = [item for item in source if item["model"] == "accounts.role"]
        mapping = {}
        for entry in role_entries:
            target_role = Role.objects.get(code=entry["fields"]["code"])
            mapping[entry["pk"]] = {
                "target_pk": target_role.pk,
                "status": "ROLE_PK_REMAP_REQUIRED",
                "role_key": entry["fields"]["code"],
                "compared_fields": {"code": entry["fields"]["code"]},
                "field_hash": "hash",
            }
        rewritten = rewrite_fixture_for_seeded_roles(source, mapping)
        for item in rewritten:
            if item["model"] != "accounts.profile":
                continue
            before = source_profiles[item["pk"]]
            after = item["fields"]
            self.assertEqual(before["user"], after["user"])
            self.assertEqual(before["photo"], after["photo"])
            self.assertEqual(before["first_name"], after["first_name"])
            self.assertEqual(before["last_name"], after["last_name"])
            self.assertEqual(before["vulgo"], after["vulgo"])
            self.assertNotEqual(before["roles"], after["roles"])

    def test_build_role_mapping_payload_contains_no_profile_data(self):
        fixture = self.write_fixture(self.build_role_fixture_entries(), name="roles-payload.json")
        stdout = io.StringIO()
        call_command(
            "audit_content_import",
            str(fixture),
            media_root=str(self.media_root),
            role_strategy="seed-match",
            json=True,
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())
        mapping_payload = build_role_mapping_payload(type("Result", (), payload)())
        rendered = json.dumps(mapping_payload)
        self.assertNotIn("first_name", rendered)
        self.assertNotIn("last_name", rendered)

    def test_prepare_command_creates_target_fixture_mapping_and_manifest(self):
        source_payload = self.build_full_source_fixture(pk_transform=lambda pk: pk + 1000)
        source_fixture = self.write_fixture(source_payload, name="avf-content-20260804.json")
        source_manifest = self.write_manifest(
            self.source_manifest_payload(source_fixture, source_payload),
            name="manifest-20260804.json",
        )
        result = self.run_prepare_command(source_fixture, source_manifest)

        target_payload = json.loads(result["target_fixture"].read_text(encoding="utf-8"))
        counts = Counter(item["model"] for item in target_payload)
        self.assertNotIn("accounts.role", counts)
        self.assertEqual(counts["auth.user"], 22)
        self.assertEqual(counts["accounts.profile"], 22)
        self.assertEqual(counts["events.event"], 6)
        self.assertEqual(len(target_payload), 50)

        role_mapping_payload = json.loads(result["role_mapping"].read_text(encoding="utf-8"))
        self.assertEqual(len(role_mapping_payload["roles"]), 13)
        self.assertGreater(role_mapping_payload["role_status_counts"]["ROLE_PK_REMAP_REQUIRED"], 0)

        manifest_payload = json.loads(result["target_manifest"].read_text(encoding="utf-8"))
        self.assertEqual(manifest_payload["excluded_role_objects"], 13)
        self.assertEqual(manifest_payload["final_object_counts"]["auth.user"], 22)
        self.assertEqual(manifest_payload["final_object_counts"]["accounts.profile"], 22)
        self.assertEqual(manifest_payload["final_object_counts"]["events.event"], 6)
        self.assertEqual(len(manifest_payload["target_fixture_sha256"]), 64)
        self.assertEqual(len(manifest_payload["role_mapping_sha256"]), 64)
        self.assertNotIn("manifest_sha256", manifest_payload)

        source_payload_after = json.loads(source_fixture.read_text(encoding="utf-8"))
        self.assertEqual(source_payload_after, source_payload)

    def test_prepare_command_does_not_modify_database(self):
        before = (User.objects.count(), Role.objects.count(), Event.objects.count())
        source_payload = self.build_full_source_fixture(pk_transform=lambda pk: pk + 1000)
        source_fixture = self.write_fixture(source_payload, name="source.json")
        source_manifest = self.write_manifest(self.source_manifest_payload(source_fixture, source_payload), name="source-manifest.json")
        self.run_prepare_command(source_fixture, source_manifest)
        after = (User.objects.count(), Role.objects.count(), Event.objects.count())
        self.assertEqual(before, after)
