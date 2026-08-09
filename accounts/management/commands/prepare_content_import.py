import json
import platform
from collections import Counter
from datetime import datetime
from pathlib import Path

import django
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.management.commands.audit_content_import import (
    ALLOWED_MODEL_LABELS,
    FixtureAuditor,
    build_role_mapping_payload,
    rewrite_fixture_for_seeded_roles,
    sha256_file,
)


class Command(BaseCommand):
    help = "Builds a role-safe target fixture, role mapping, and manifest without writing to the database."

    def add_arguments(self, parser):
        parser.add_argument("source_fixture", help="Path to the source JSON fixture file.")
        parser.add_argument("--source-manifest", required=True, help="Path to the existing source manifest.")
        parser.add_argument("--output-fixture", required=True, help="Path for the rewritten target fixture.")
        parser.add_argument("--output-role-mapping", required=True, help="Path for the role mapping JSON.")
        parser.add_argument("--output-manifest", required=True, help="Path for the target manifest JSON.")
        parser.add_argument("--media-root", default="", help="Override MEDIA_ROOT used for FileField/ImageField checks.")
        parser.add_argument("--database", default="default", help="Database alias to audit against. Default: default")

    def handle(self, *args, **options):
        source_fixture = Path(options["source_fixture"]).expanduser()
        source_manifest = Path(options["source_manifest"]).expanduser()
        output_fixture = Path(options["output_fixture"]).expanduser()
        output_role_mapping = Path(options["output_role_mapping"]).expanduser()
        output_manifest = Path(options["output_manifest"]).expanduser()
        media_root = Path(options["media_root"]).expanduser() if options["media_root"] else Path(settings.MEDIA_ROOT)
        database = options["database"]

        if database not in settings.DATABASES:
            raise CommandError(f"Unknown database alias: {database}")

        if source_fixture == output_fixture:
            raise CommandError("Source fixture and output fixture must be different files.")
        if source_manifest == output_manifest:
            raise CommandError("Source manifest and output manifest must be different files.")

        fixture_objects = self._load_json_array(source_fixture)
        source_manifest_payload = self._load_json_object(source_manifest)

        auditor = FixtureAuditor(fixture_objects, media_root, database, role_strategy="seed-match")
        audit_result = auditor.audit_role_seed_preparation()
        if audit_result.has_errors:
            raise CommandError("Seed-match audit failed; target artifacts were not written.")

        target_fixture_objects = rewrite_fixture_for_seeded_roles(fixture_objects, auditor.role_mapping)
        self._validate_target_fixture(target_fixture_objects)

        role_mapping_payload = build_role_mapping_payload(audit_result)
        target_manifest_payload = self._build_target_manifest(
            source_fixture=source_fixture,
            source_manifest=source_manifest_payload,
            target_fixture_objects=target_fixture_objects,
            role_mapping_payload=role_mapping_payload,
            output_fixture=output_fixture,
            output_role_mapping=output_role_mapping,
            database=database,
        )

        output_fixture.parent.mkdir(parents=True, exist_ok=True)
        output_role_mapping.parent.mkdir(parents=True, exist_ok=True)
        output_manifest.parent.mkdir(parents=True, exist_ok=True)

        output_fixture.write_text(json.dumps(target_fixture_objects, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        output_role_mapping.write_text(json.dumps(role_mapping_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        target_manifest_payload["target_fixture_sha256"] = sha256_file(output_fixture)
        target_manifest_payload["role_mapping_sha256"] = sha256_file(output_role_mapping)
        output_manifest.write_text(json.dumps(target_manifest_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        self.stdout.write(f"Source fixture: {source_fixture}")
        self.stdout.write(f"Target fixture: {output_fixture}")
        self.stdout.write(f"Role mapping: {output_role_mapping}")
        self.stdout.write(f"Target manifest: {output_manifest}")
        self.stdout.write(f"Final object counts: {target_manifest_payload['final_object_counts']}")
        self.stdout.write(f"Role status counts: {role_mapping_payload['role_status_counts']}")

    def _load_json_array(self, path):
        payload = self._load_json(path)
        if not isinstance(payload, list):
            raise CommandError(f"Expected JSON array in {path}")
        return payload

    def _load_json_object(self, path):
        payload = self._load_json(path)
        if not isinstance(payload, dict):
            raise CommandError(f"Expected JSON object in {path}")
        return payload

    def _load_json(self, path):
        if not path.exists() or not path.is_file():
            raise CommandError(f"JSON file not found: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Could not read JSON file {path}: {exc}") from exc

    def _validate_target_fixture(self, payload):
        counts = Counter(item["model"] for item in payload)
        if ROLE_MODEL_LABEL in counts:
            raise CommandError("Target fixture still contains accounts.role objects.")
        if len(payload) != 50:
            raise CommandError(f"Target fixture must contain exactly 50 objects, found {len(payload)}.")
        for model_label in counts:
            if model_label not in ALLOWED_MODEL_LABELS:
                raise CommandError(f"Target fixture contains disallowed model: {model_label}")

    def _build_target_manifest(
        self,
        *,
        source_fixture,
        source_manifest,
        target_fixture_objects,
        role_mapping_payload,
        output_fixture,
        output_role_mapping,
        database,
    ):
        source_counts = source_manifest.get("object_counts", {})
        final_counts = dict(sorted(Counter(item["model"] for item in target_fixture_objects).items()))
        identical_pk_count = sum(1 for role in role_mapping_payload["roles"] if role["status"] == "ROLE_PK_MATCH")
        remap_count = sum(1 for role in role_mapping_payload["roles"] if role["status"] == "ROLE_PK_REMAP_REQUIRED")
        return {
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "role_strategy": "seed-match",
            "source_fixture": str(source_fixture),
            "source_fixture_sha256": source_manifest.get("fixture_sha256", ""),
            "target_fixture": str(output_fixture),
            "target_fixture_sha256": "",
            "original_object_counts": source_counts,
            "final_object_counts": final_counts,
            "excluded_role_objects": int(source_counts.get("accounts.role", 0)),
            "allowed_model_labels": sorted(ALLOWED_MODEL_LABELS),
            "role_mapping_file": str(output_role_mapping),
            "role_mapping_sha256": "",
            "role_business_key_fields": role_mapping_payload["role_business_key_fields"],
            "role_compared_fields": role_mapping_payload["role_compared_fields"],
            "role_excluded_fields": role_mapping_payload["role_excluded_fields"],
            "role_status_counts": role_mapping_payload["role_status_counts"],
            "identical_role_pk_count": identical_pk_count,
            "role_pk_remap_count": remap_count,
            "warnings": [],
            "source_database_path": source_manifest.get("source_database_path", ""),
            "source_manifest": source_manifest,
            "django_version": django.get_version(),
            "python_version": platform.python_version(),
            "database_alias": database,
            "worktree_status": source_manifest.get("worktree_status", "git-unavailable"),
        }


ROLE_MODEL_LABEL = "accounts.role"
