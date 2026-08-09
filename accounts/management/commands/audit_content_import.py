import hashlib
import json
import re
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path, PurePosixPath, PureWindowsPath

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import models

from accounts.models import Role


ALLOWED_MODEL_LABELS = frozenset(
    {
        "auth.user",
        "accounts.role",
        "accounts.profile",
        "events.event",
        "events.eventsignupcolumn",
        "events.eventsignup",
    }
)

ROLE_MODEL_LABEL = "accounts.role"
PROFILE_MODEL_LABEL = "accounts.profile"
ROLE_STRATEGIES = ("none", "seed-match", "target-seeded")
ROLE_BUSINESS_KEY_FIELD_NAMES = ("code",)
ROLE_COMPARE_FIELD_NAMES = ("code",)
ROLE_EXCLUDED_FIELD_NAMES = ("id",)

SENSITIVE_FIELD_NAMES = frozenset(
    {
        "username",
        "first_name",
        "last_name",
        "email",
        "password",
        "description",
        "short_description",
        "vulgo",
        "location",
    }
)


class AuditResult:
    def __init__(self):
        self.findings = []
        self.warnings = []
        self.model_counts = Counter()
        self.expected_inserts = Counter()
        self.media_references = 0
        self.missing_media_files = 0
        self.role_strategy = "none"
        self.role_business_key_fields = list(ROLE_BUSINESS_KEY_FIELD_NAMES)
        self.role_compared_fields = list(ROLE_COMPARE_FIELD_NAMES)
        self.role_excluded_fields = list(ROLE_EXCLUDED_FIELD_NAMES)
        self.role_matches = []
        self.role_status_counts = Counter()

    def add_finding(self, code, model=None, pk=None, field=None, detail=None):
        finding = {
            "code": code,
            "model": model or "",
            "pk": pk if pk is not None else "",
            "field": field or "",
        }
        if detail:
            finding["detail"] = detail
        self.findings.append(finding)
        if code in {"MISSING_MEDIA_FILE"}:
            self.missing_media_files += 1

    def add_warning(self, code, model=None, pk=None, field=None, detail=None):
        warning = {
            "code": code,
            "model": model or "",
            "pk": pk if pk is not None else "",
            "field": field or "",
        }
        if detail:
            warning["detail"] = detail
        self.warnings.append(warning)

    def add_role_match(self, match):
        self.role_matches.append(match)
        self.role_status_counts[match["status"]] += 1
        self.role_status_counts["ROLE_SEED_MATCH"] += 1

    @property
    def warning_count(self):
        return len(self.warnings)

    @property
    def has_errors(self):
        return bool(self.findings)

    def summary(self):
        return {
            "allowed_model_labels": sorted(ALLOWED_MODEL_LABELS),
            "model_counts": dict(sorted(self.model_counts.items())),
            "expected_inserts": dict(sorted(self.expected_inserts.items())),
            "findings": self.findings,
            "conflicts": len(self.findings),
            "warnings": self.warnings,
            "warning_count": self.warning_count,
            "media_references": self.media_references,
            "missing_media_files": self.missing_media_files,
            "role_strategy": self.role_strategy,
            "role_business_key_fields": self.role_business_key_fields,
            "role_compared_fields": self.role_compared_fields,
            "role_excluded_fields": self.role_excluded_fields,
            "role_matches": self.role_matches,
            "role_status_counts": dict(sorted(self.role_status_counts.items())),
            "result": "FAIL" if self.has_errors else "PASS",
        }


class FixtureFormatError(Exception):
    pass


class FixtureAuditor:
    def __init__(self, fixture_objects, media_root, database, role_strategy="none"):
        self.fixture_objects = fixture_objects
        self.media_root = media_root.resolve()
        self.database = database
        self.role_strategy = role_strategy
        self.result = AuditResult()
        self.result.role_strategy = role_strategy
        self.allowed_models = self._build_allowed_model_map()
        self.fixture_index = defaultdict(dict)
        self.fixture_by_model = defaultdict(list)
        self.model_metadata = {}
        self.role_mapping = {}

    def audit(self):
        self._index_fixture()
        for model_label, entries in self.fixture_by_model.items():
            model = self.allowed_models[model_label]
            self.model_metadata[model_label] = self._build_model_metadata(model)
            self.result.model_counts[model_label] = len(entries)
            self.result.expected_inserts[model_label] = len(entries)

        self._audit_role_strategy()

        for model_label, entries in self.fixture_by_model.items():
            model = self.allowed_models[model_label]
            self._audit_model_entries(model_label, model, entries)

        if self.role_strategy == "seed-match":
            self._validate_profile_role_mapping()

        return self.result

    def audit_role_seed_preparation(self):
        self._index_fixture()
        for model_label, entries in self.fixture_by_model.items():
            self.result.model_counts[model_label] = len(entries)
            self.result.expected_inserts[model_label] = len(entries)
        self._audit_role_strategy()
        if self.role_strategy == "seed-match":
            self._validate_profile_role_mapping()
        return self.result

    def _audit_role_strategy(self):
        if self.role_strategy == "none":
            return

        if self.role_strategy == "target-seeded":
            for entry in self.fixture_by_model.get(ROLE_MODEL_LABEL, []):
                self.result.add_finding("ROLE_OBJECTS_NOT_ALLOWED", model=ROLE_MODEL_LABEL, pk=entry["pk"])
            return

        if self.role_strategy != "seed-match":
            raise FixtureFormatError(f"Unsupported role strategy: {self.role_strategy}")

        role_entries = self.fixture_by_model.get(ROLE_MODEL_LABEL, [])
        target_roles = list(Role.objects.using(self.database).order_by("pk"))

        source_by_key = {}
        for entry in role_entries:
            key = self._role_business_key_from_fields(entry["fields"])
            if key is None:
                self.result.add_finding("ROLE_KEY_MISSING", model=ROLE_MODEL_LABEL, pk=entry["pk"], field="code")
                continue
            if key in source_by_key:
                self.result.add_finding("ROLE_KEY_DUPLICATE", model=ROLE_MODEL_LABEL, pk=entry["pk"], field="code")
                continue
            source_by_key[key] = entry

        target_by_key = {}
        for role in target_roles:
            key = self._role_business_key_from_instance(role)
            if key in target_by_key:
                self.result.add_finding("ROLE_KEY_DUPLICATE", model=ROLE_MODEL_LABEL, pk=role.pk, field="code")
                continue
            target_by_key[key] = role

        for key, source_entry in source_by_key.items():
            target_role = target_by_key.get(key)
            if target_role is None:
                self.result.add_finding(
                    "ROLE_MISSING_ON_TARGET",
                    model=ROLE_MODEL_LABEL,
                    pk=source_entry["pk"],
                    field="code",
                    detail=f"role_key={self._render_role_key(key)}",
                )
                continue

            source_values = self._role_comparison_values_from_fields(source_entry["fields"])
            target_values = self._role_comparison_values_from_instance(target_role)
            if source_values != target_values:
                self.result.add_finding(
                    "ROLE_FIELD_MISMATCH",
                    model=ROLE_MODEL_LABEL,
                    pk=source_entry["pk"],
                    field="code",
                    detail=f"role_key={self._render_role_key(key)}",
                )
                continue

            source_pk = source_entry["pk"]
            target_pk = target_role.pk
            status = "ROLE_PK_MATCH" if source_pk == target_pk else "ROLE_PK_REMAP_REQUIRED"
            field_hash = hashlib.sha256(
                json.dumps(source_values, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            match = {
                "role_key": self._render_role_key(key),
                "source_pk": source_pk,
                "target_pk": target_pk,
                "status": status,
                "compared_fields": dict(source_values),
                "field_hash": field_hash,
            }
            self.result.add_role_match(match)
            self.role_mapping[source_pk] = {
                "target_pk": target_pk,
                "status": status,
                "role_key": self._render_role_key(key),
                "compared_fields": dict(source_values),
                "field_hash": field_hash,
            }

        for key, target_role in target_by_key.items():
            if key not in source_by_key:
                self.result.add_finding(
                    "ROLE_EXTRA_ON_TARGET",
                    model=ROLE_MODEL_LABEL,
                    pk=target_role.pk,
                    field="code",
                    detail=f"role_key={self._render_role_key(key)}",
                )

    def _build_allowed_model_map(self):
        model_map = {}
        for model in apps.get_models():
            label = model._meta.label_lower
            if label in ALLOWED_MODEL_LABELS:
                model_map[label] = model
        return model_map

    def _index_fixture(self):
        for index, item in enumerate(self.fixture_objects):
            if not isinstance(item, dict):
                raise FixtureFormatError(f"Fixture item at index {index} must be an object.")

            model_label = str(item.get("model", "")).strip().lower()
            if not model_label:
                raise FixtureFormatError(f'Fixture item at index {index} is missing "model".')

            if model_label not in self.allowed_models:
                if model_label in self._known_model_labels():
                    self.result.add_finding("MODEL_NOT_ALLOWED", model=model_label, pk=item.get("pk", ""))
                else:
                    self.result.add_finding("UNKNOWN_MODEL", model=model_label, pk=item.get("pk", ""))
                continue

            if "pk" not in item:
                raise FixtureFormatError(f'Fixture item for {model_label} is missing "pk".')

            pk = item["pk"]
            fields = item.get("fields")
            if not isinstance(fields, dict):
                raise FixtureFormatError(f'Fixture item for {model_label} pk={pk} must contain an object "fields".')

            if pk in self.fixture_index[model_label]:
                self.result.add_finding("DUPLICATE_PK_IN_FIXTURE", model=model_label, pk=pk)
                continue

            entry = {
                "model": model_label,
                "pk": pk,
                "fields": fields,
            }
            self.fixture_index[model_label][pk] = entry
            self.fixture_by_model[model_label].append(entry)

    def _audit_model_entries(self, model_label, model, entries):
        metadata = self.model_metadata[model_label]
        seen_unique_fields = defaultdict(dict)
        seen_unique_constraints = defaultdict(dict)

        for entry in entries:
            pk = entry["pk"]
            fields = entry["fields"]

            if not self._skip_pk_conflict_check(model_label):
                self._check_pk_conflict(model_label, model, pk)
            self._check_unexpected_fields(model_label, pk, fields, metadata)
            self._check_relation_fields(model_label, pk, fields, metadata)
            if not self._skip_unique_checks(model_label):
                self._check_unique_fields(model_label, model, pk, fields, metadata, seen_unique_fields)
                self._check_unique_constraints(model_label, model, pk, fields, metadata, seen_unique_constraints)
            self._check_file_fields(model_label, pk, fields, metadata)

    def _skip_pk_conflict_check(self, model_label):
        return self.role_strategy == "seed-match" and model_label == ROLE_MODEL_LABEL

    def _skip_unique_checks(self, model_label):
        return self.role_strategy == "seed-match" and model_label == ROLE_MODEL_LABEL

    def _check_pk_conflict(self, model_label, model, pk):
        if model._default_manager.using(self.database).filter(pk=pk).exists():
            self.result.add_finding("PK_CONFLICT", model=model_label, pk=pk)

    def _check_unexpected_fields(self, model_label, pk, fields, metadata):
        allowed = metadata["allowed_field_names"]
        for field_name in fields.keys():
            if field_name not in allowed:
                self.result.add_finding("UNEXPECTED_FIELD", model=model_label, pk=pk, field=field_name)

    def _check_relation_fields(self, model_label, pk, fields, metadata):
        for field_name, relation in metadata["relations"].items():
            if field_name not in fields:
                continue

            value = fields[field_name]
            target_label = relation["target_label"]
            target_model = relation["target_model"]

            if relation["kind"] == "m2m":
                if not isinstance(value, list):
                    self.result.add_finding("INVALID_FIELD_VALUE", model=model_label, pk=pk, field=field_name)
                    continue

                for target_pk in value:
                    if self._target_exists(model_label, field_name, target_label, target_model, target_pk):
                        continue
                    code = "PROFILE_ROLE_UNKNOWN" if self._is_profile_role_reference(model_label, field_name) else "MISSING_M2M_TARGET"
                    self.result.add_finding(code, model=model_label, pk=pk, field=field_name)
            else:
                if value in (None, ""):
                    if not relation["nullable"]:
                        self.result.add_finding("MISSING_FOREIGN_KEY", model=model_label, pk=pk, field=field_name)
                    continue

                if self._target_exists(model_label, field_name, target_label, target_model, value):
                    if relation["kind"] == "o2o":
                        self._check_onetoone_conflict(model_label, pk, field_name, relation, value)
                    continue

                self.result.add_finding("MISSING_FOREIGN_KEY", model=model_label, pk=pk, field=field_name)

    def _check_onetoone_conflict(self, model_label, pk, field_name, relation, value):
        target_model = relation["source_model"]
        field = relation["field"]
        queryset = target_model._default_manager.using(self.database).filter(**{field.name: value})
        if queryset.exclude(pk=pk).exists():
            self.result.add_finding("ONETOONE_CONFLICT", model=model_label, pk=pk, field=field_name)

    def _check_unique_fields(self, model_label, model, pk, fields, metadata, seen_unique_fields):
        for field_name in metadata["unique_fields"]:
            if field_name not in fields:
                continue

            value = fields[field_name]
            field = metadata["field_map"][field_name]
            if value is None and field.null:
                continue

            if value in seen_unique_fields[field_name] and seen_unique_fields[field_name][value] != pk:
                self.result.add_finding("UNIQUE_CONFLICT", model=model_label, pk=pk, field=field_name)
            else:
                seen_unique_fields[field_name][value] = pk

            queryset = model._default_manager.using(self.database).filter(**{field_name: value})
            if queryset.exclude(pk=pk).exists():
                self.result.add_finding("UNIQUE_CONFLICT", model=model_label, pk=pk, field=field_name)

    def _check_unique_constraints(self, model_label, model, pk, fields, metadata, seen_unique_constraints):
        for constraint_fields in metadata["unique_constraints"]:
            if any(field_name not in fields for field_name in constraint_fields):
                continue

            values = tuple(fields[field_name] for field_name in constraint_fields)
            key = "|".join(constraint_fields)
            if values in seen_unique_constraints[key] and seen_unique_constraints[key][values] != pk:
                self.result.add_finding("UNIQUE_CONFLICT", model=model_label, pk=pk, field=key)
            else:
                seen_unique_constraints[key][values] = pk

            query_kwargs = dict(zip(constraint_fields, values))
            queryset = model._default_manager.using(self.database).filter(**query_kwargs)
            if queryset.exclude(pk=pk).exists():
                self.result.add_finding("UNIQUE_CONFLICT", model=model_label, pk=pk, field=key)

    def _check_file_fields(self, model_label, pk, fields, metadata):
        for field_name in metadata["file_fields"]:
            if field_name not in fields:
                continue

            value = fields[field_name]
            if not value:
                continue

            self.result.media_references += 1
            if not isinstance(value, str):
                self.result.add_finding("INVALID_FIELD_VALUE", model=model_label, pk=pk, field=field_name)
                continue

            path_error = self._validate_media_path(value)
            if path_error is not None:
                self.result.add_finding(path_error, model=model_label, pk=pk, field=field_name)
                continue

            resolved_path = (self.media_root / PurePosixPath(value)).resolve()
            if not resolved_path.exists():
                self.result.add_finding("MISSING_MEDIA_FILE", model=model_label, pk=pk, field=field_name)

    def _validate_profile_role_mapping(self):
        for entry in self.fixture_by_model.get(PROFILE_MODEL_LABEL, []):
            role_ids = entry["fields"].get("roles", [])
            if not isinstance(role_ids, list):
                continue
            for role_id in role_ids:
                if role_id not in self.role_mapping:
                    self.result.add_finding("PROFILE_ROLE_UNKNOWN", model=PROFILE_MODEL_LABEL, pk=entry["pk"], field="roles")

    def _validate_media_path(self, value):
        if re.match(r"^[a-zA-Z]:[\\/]", value):
            return "INVALID_MEDIA_PATH"
        if re.match(r"^[a-zA-Z]+://", value):
            return "INVALID_MEDIA_PATH"
        if PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute():
            return "INVALID_MEDIA_PATH"

        parts = PurePosixPath(value).parts
        if ".." in parts:
            return "INVALID_MEDIA_PATH"

        try:
            (self.media_root / PurePosixPath(value)).resolve().relative_to(self.media_root)
        except ValueError:
            return "INVALID_MEDIA_PATH"

        return None

    def _target_exists(self, source_label, source_field_name, target_label, target_model, target_pk):
        if self.role_strategy == "seed-match" and self._is_profile_role_reference(source_label, source_field_name):
            return target_pk in self.role_mapping
        if target_pk in self.fixture_index[target_label]:
            return True
        return target_model._default_manager.using(self.database).filter(pk=target_pk).exists()

    def _is_profile_role_reference(self, source_label, source_field_name):
        return source_label == PROFILE_MODEL_LABEL and source_field_name == "roles"

    def _known_model_labels(self):
        return {model._meta.label_lower for model in apps.get_models()}

    def _build_model_metadata(self, model):
        field_map = {}
        allowed_field_names = set()
        relations = {}
        file_fields = set()
        unique_fields = set()

        for field in model._meta.get_fields():
            if not getattr(field, "concrete", False) and not getattr(field, "many_to_many", False):
                continue
            if getattr(field, "auto_created", False) and not getattr(field, "concrete", False):
                continue

            allowed_field_names.add(field.name)
            field_map[field.name] = field

            if isinstance(field, (models.FileField, models.ImageField)):
                file_fields.add(field.name)

            if getattr(field, "unique", False) and not getattr(field, "primary_key", False):
                unique_fields.add(field.name)

            if getattr(field, "many_to_many", False):
                relations[field.name] = {
                    "kind": "m2m",
                    "field": field,
                    "target_model": field.remote_field.model,
                    "target_label": field.remote_field.model._meta.label_lower,
                    "nullable": True,
                }
            elif getattr(field, "one_to_one", False):
                relations[field.name] = {
                    "kind": "o2o",
                    "field": field,
                    "source_model": model,
                    "target_model": field.remote_field.model,
                    "target_label": field.remote_field.model._meta.label_lower,
                    "nullable": getattr(field, "null", False),
                }
            elif getattr(field, "many_to_one", False):
                relations[field.name] = {
                    "kind": "fk",
                    "field": field,
                    "target_model": field.remote_field.model,
                    "target_label": field.remote_field.model._meta.label_lower,
                    "nullable": getattr(field, "null", False),
                }

        unique_constraints = []
        for constraint in model._meta.constraints:
            if (
                isinstance(constraint, models.UniqueConstraint)
                and constraint.fields
                and not constraint.condition
                and not constraint.expressions
            ):
                unique_constraints.append(tuple(constraint.fields))

        return {
            "allowed_field_names": allowed_field_names,
            "field_map": field_map,
            "relations": relations,
            "file_fields": file_fields,
            "unique_fields": unique_fields,
            "unique_constraints": unique_constraints,
        }

    def _role_business_key_from_fields(self, fields):
        code = fields.get("code")
        if not code:
            return None
        return (code,)

    def _role_business_key_from_instance(self, role):
        return (role.code,)

    def _role_comparison_values_from_fields(self, fields):
        return {field_name: fields.get(field_name) for field_name in ROLE_COMPARE_FIELD_NAMES}

    def _role_comparison_values_from_instance(self, role):
        return {field_name: getattr(role, field_name) for field_name in ROLE_COMPARE_FIELD_NAMES}

    def _render_role_key(self, key):
        return "|".join(str(value) for value in key)


def load_fixture_payload(fixture_path):
    fixture_path = Path(fixture_path).expanduser()
    if not fixture_path.exists() or not fixture_path.is_file():
        raise SystemExit(2)

    try:
        raw = fixture_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(2) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(2) from exc

    if not isinstance(payload, list):
        raise SystemExit(2)

    return payload


def rewrite_fixture_for_seeded_roles(fixture_objects, role_mapping):
    rewritten = []
    for item in fixture_objects:
        if str(item.get("model", "")).lower() == ROLE_MODEL_LABEL:
            continue

        copied = deepcopy(item)
        if str(copied.get("model", "")).lower() == PROFILE_MODEL_LABEL:
            roles = copied.get("fields", {}).get("roles", [])
            copied["fields"]["roles"] = [role_mapping[role_id]["target_pk"] for role_id in roles]
        rewritten.append(copied)
    return rewritten


def build_role_mapping_payload(audit_result):
    return {
        "role_strategy": audit_result.role_strategy,
        "role_business_key_fields": audit_result.role_business_key_fields,
        "role_compared_fields": audit_result.role_compared_fields,
        "role_excluded_fields": audit_result.role_excluded_fields,
        "role_status_counts": dict(sorted(audit_result.role_status_counts.items())),
        "roles": audit_result.role_matches,
    }


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = "Audits a restricted content fixture for a safe SQLite to MariaDB import without writing any data."

    def add_arguments(self, parser):
        parser.add_argument("fixture", help="Path to the JSON fixture file to audit.")
        parser.add_argument("--media-root", default="", help="Override MEDIA_ROOT used for FileField/ImageField checks.")
        parser.add_argument("--database", default="default", help="Database alias to audit against. Default: default")
        parser.add_argument(
            "--role-strategy",
            default="none",
            choices=ROLE_STRATEGIES,
            help="Role handling strategy. Use seed-match for source fixtures and target-seeded for rewritten fixtures.",
        )
        parser.add_argument("--json", action="store_true", help="Emit the summary as JSON.")

    def handle(self, *args, **options):
        fixture_path = Path(options["fixture"]).expanduser()
        media_root = Path(options["media_root"]).expanduser() if options["media_root"] else Path(settings.MEDIA_ROOT)
        database = options["database"]
        role_strategy = options["role_strategy"]

        if database not in settings.DATABASES:
            raise CommandError(f"Unknown database alias: {database}")

        fixture_objects = self._load_fixture(fixture_path)
        auditor = FixtureAuditor(fixture_objects, media_root, database, role_strategy=role_strategy)
        result = auditor.audit()

        if options["json"]:
            self.stdout.write(json.dumps(result.summary(), indent=2, sort_keys=True))
        else:
            self._render_human_summary(result, fixture_path, media_root, database)

        if result.has_errors:
            raise CommandError("AUDIT RESULT: FAIL")

        if not options["json"]:
            self.stdout.write(self.style.SUCCESS("AUDIT RESULT: PASS"))

    def _load_fixture(self, fixture_path):
        if not fixture_path.exists() or not fixture_path.is_file():
            self.stderr.write(f"Fixture not found: {fixture_path}")
            raise SystemExit(2)

        try:
            raw = fixture_path.read_text(encoding="utf-8")
        except OSError as exc:
            self.stderr.write(f"Fixture could not be read: {exc}")
            raise SystemExit(2) from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.stderr.write(f"Fixture is not valid JSON: {exc}")
            raise SystemExit(2) from exc

        if not isinstance(payload, list):
            self.stderr.write("Fixture root must be a JSON array.")
            raise SystemExit(2)

        return payload

    def _render_human_summary(self, result, fixture_path, media_root, database):
        self.stdout.write(f"Fixture: {fixture_path}")
        self.stdout.write(f"Database alias: {database}")
        self.stdout.write(f"Media root: {media_root}")
        self.stdout.write(f"Role strategy: {result.role_strategy}")
        self.stdout.write("Allowed models: " + ", ".join(sorted(ALLOWED_MODEL_LABELS)))
        if result.role_strategy != "none":
            self.stdout.write("Role business key: " + ", ".join(result.role_business_key_fields))
            self.stdout.write("Role compared fields: " + ", ".join(result.role_compared_fields))
            self.stdout.write("Role excluded fields: " + ", ".join(result.role_excluded_fields))
        for model_label, count in sorted(result.model_counts.items()):
            self.stdout.write(f"Model {model_label}: objects={count} inserts={result.expected_inserts[model_label]}")
        if result.role_matches:
            for match in result.role_matches:
                self.stdout.write(
                    "Role "
                    f'{match["status"]}: key={match["role_key"]} source_pk={match["source_pk"]} target_pk={match["target_pk"]}'
                )
        self.stdout.write(f"Role status counts: {dict(sorted(result.role_status_counts.items()))}")
        self.stdout.write(f"Media references={result.media_references} missing_media_files={result.missing_media_files}")
        for warning in result.warnings:
            self.stdout.write(
                f'Warning {warning["code"]}: model={warning["model"]} pk={warning["pk"]} field={warning["field"]}'
            )
        if result.findings:
            for finding in result.findings:
                self.stdout.write(
                    f'Finding {finding["code"]}: model={finding["model"]} pk={finding["pk"]} field={finding["field"]}'
                )
