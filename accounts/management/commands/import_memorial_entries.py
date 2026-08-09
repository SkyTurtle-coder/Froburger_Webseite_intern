import csv
import unicodedata
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import MemorialEntry


class Command(BaseCommand):
    help = "Importiert historische Totentafel-Einträge aus einer CSV-Datei."

    required_columns = {
        "display_name",
        "birth_date",
        "birth_date_display",
        "death_date",
        "death_date_display",
        "is_honorary_member",
        "legacy_marker",
        "sort_order",
        "is_published",
    }

    def add_arguments(self, parser):
        parser.add_argument("csv_file")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        csv_file = Path(options["csv_file"])
        if not csv_file.exists():
            raise CommandError(f"Datei nicht gefunden: {csv_file}")

        summary = {
            "rows": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "conflicts": 0,
            "failed": 0,
        }
        operations = []

        with csv_file.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = set(reader.fieldnames or [])
            if not self.required_columns.issubset(fieldnames):
                missing = ", ".join(sorted(self.required_columns - fieldnames))
                raise CommandError(f"CSV muss diese Spalten enthalten. Fehlend: {missing}")

            for line_number, row in enumerate(reader, start=2):
                summary["rows"] += 1
                try:
                    payload = self.normalize_row(row)
                    resolution = self.find_existing_entry(payload)
                except CommandError as exc:
                    summary["failed"] += 1
                    self.stderr.write(f"Zeile {line_number}: {exc}")
                    continue

                if resolution["status"] == "conflict":
                    summary["conflicts"] += 1
                    self.stderr.write(f"Zeile {line_number}: Konflikt für {payload['display_name']}: {resolution['reason']}")
                    continue

                existing = resolution["entry"]
                if existing is None:
                    summary["created"] += 1
                    operations.append(
                        {
                            "action": "create",
                            "payload": payload,
                            "entry": None,
                        }
                    )
                    self.stdout.write(self.describe_operation(options["dry_run"], "create", payload["display_name"]))
                    continue

                changed_fields = self.changed_fields(existing, payload)
                if not changed_fields:
                    summary["skipped"] += 1
                    operations.append(
                        {
                            "action": "skip",
                            "payload": payload,
                            "entry": existing,
                            "changed_fields": [],
                        }
                    )
                    self.stdout.write(self.describe_operation(options["dry_run"], "skip", payload["display_name"]))
                    continue

                summary["updated"] += 1
                operations.append(
                    {
                        "action": "update",
                        "payload": payload,
                        "entry": existing,
                        "changed_fields": changed_fields,
                    }
                )
                self.stdout.write(self.describe_operation(options["dry_run"], "update", payload["display_name"]))

        self.stdout.write(
            "Zusammenfassung: "
            f"zeilen={summary['rows']}, "
            f"neu={summary['created']}, "
            f"aktualisiert={summary['updated']}, "
            f"übersprungen={summary['skipped']}, "
            f"konflikte={summary['conflicts']}, "
            f"fehlerhaft={summary['failed']}"
        )

        if options["dry_run"]:
            return

        if summary["conflicts"] or summary["failed"]:
            raise CommandError("Import abgebrochen, da Konflikte oder fehlerhafte Zeilen vorhanden sind.")

        try:
            with transaction.atomic():
                for operation in operations:
                    if operation["action"] == "skip":
                        continue

                    entry = operation["entry"] or MemorialEntry()
                    for field_name, value in operation["payload"].items():
                        setattr(entry, field_name, value)
                    if operation["action"] == "create":
                        entry.is_profile_generated = False
                    entry.full_clean()
                    entry.save()
        except Exception as exc:
            raise CommandError(f"Import fehlgeschlagen, es wurde nichts gespeichert: {exc}") from exc

        self.stdout.write(
            "Import abgeschlossen: "
            f"neu angelegt={summary['created']}, "
            f"aktualisiert={summary['updated']}, "
            f"übersprungen={summary['skipped']}, "
            f"konflikte={summary['conflicts']}, "
            f"fehlerhaft={summary['failed']}"
        )

    @staticmethod
    def describe_operation(is_dry_run, action, display_name):
        prefix = "[dry-run] " if is_dry_run else ""
        return f"{prefix}{action}: {display_name}"

    def normalize_row(self, row):
        display_name = (row.get("display_name") or "").strip()
        if not display_name:
            raise CommandError("display_name darf nicht leer sein.")

        import_key = (row.get("import_key") or row.get("legacy_id") or "").strip() or None
        birth_date, birth_display = self.parse_date_pair(row.get("birth_date"), row.get("birth_date_display"))
        death_date, death_display = self.parse_date_pair(row.get("death_date"), row.get("death_date_display"))
        try:
            sort_order = int((row.get("sort_order") or "0").strip() or "0")
        except ValueError as exc:
            raise CommandError(f"Ungültige Sortierung: {row.get('sort_order')}") from exc

        return {
            "display_name": display_name,
            "import_key": import_key,
            "birth_date": birth_date,
            "birth_date_display": birth_display,
            "death_date": death_date,
            "death_date_display": death_display,
            "sort_date": death_date,
            "sort_order": sort_order,
            "is_published": self.parse_bool(row.get("is_published")),
            "is_honorary_member": self.parse_bool(row.get("is_honorary_member")),
            # Kreuze werden fachlich nicht mehr verwendet und deshalb nie gespeichert.
            "legacy_marker": "",
        }

    def find_existing_entry(self, payload):
        if payload["import_key"]:
            import_key_matches = list(MemorialEntry.objects.filter(import_key=payload["import_key"]))
            return self.resolve_unique(import_key_matches, "import_key")

        strategies = (
            (
                "verknüpftes Mitgliederprofil",
                lambda entry: entry.member_profile_id is not None and self.name_matches(entry, payload) and self.death_matches(entry, payload),
            ),
            (
                "Anzeigename + exaktes Todesdatum",
                lambda entry: bool(payload["death_date"]) and self.name_matches(entry, payload) and entry.death_date == payload["death_date"],
            ),
            (
                "Anzeigename + historischer Todes-Anzeigetext",
                lambda entry: bool(payload["death_date_display"]) and self.name_matches(entry, payload) and entry.death_date_display.strip() == payload["death_date_display"],
            ),
            (
                "Anzeigename eindeutig",
                lambda entry: self.name_matches(entry, payload),
            ),
        )

        queryset = MemorialEntry.objects.select_related("member_profile", "obituary_document").all()
        for label, matcher in strategies:
            matches = [entry for entry in queryset if matcher(entry)]
            if not matches:
                continue
            return self.resolve_unique(matches, label)

        return {"status": "ok", "entry": None}

    @staticmethod
    def resolve_unique(matches, label):
        if not matches:
            return {"status": "ok", "entry": None}
        if len(matches) == 1:
            return {"status": "ok", "entry": matches[0]}
        return {
            "status": "conflict",
            "entry": None,
            "reason": f"mehrdeutige Zuordnung über {label} ({len(matches)} Treffer)",
        }

    def changed_fields(self, existing, payload):
        changed = []
        for field_name, value in payload.items():
            if getattr(existing, field_name) != value:
                changed.append(field_name)
        return changed

    def name_matches(self, entry, payload):
        payload_name = self.normalize_identifier(payload["display_name"])
        candidate_names = {self.normalize_identifier(entry.display_name)}
        if entry.member_profile_id:
            candidate_names.add(self.normalize_identifier(entry.member_profile.memorial_display_name))
        return payload_name in candidate_names

    @staticmethod
    def death_matches(entry, payload):
        if payload["death_date"]:
            return entry.death_date == payload["death_date"]
        if payload["death_date_display"]:
            return entry.death_date_display.strip() == payload["death_date_display"]
        return not entry.death_date and not entry.death_date_display.strip()

    @staticmethod
    def normalize_identifier(value):
        normalized = unicodedata.normalize("NFKC", (value or "").strip())
        return " ".join(normalized.split()).casefold()

    def parse_date_pair(self, exact_value, display_value):
        exact_value = (exact_value or "").strip()
        display_value = (display_value or "").strip()
        if exact_value:
            try:
                parsed = self.parse_iso_or_eu_date(exact_value)
            except ValueError as exc:
                raise CommandError(str(exc))
            return parsed, ""
        if display_value.startswith("00.00."):
            display_value = display_value.split("00.00.", 1)[1]
        return None, display_value

    @staticmethod
    def parse_iso_or_eu_date(value):
        for date_format in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(value, date_format).date()
            except ValueError:
                continue
        raise ValueError(f"Ungültiges Datum: {value}")

    @staticmethod
    def parse_bool(value):
        normalized = (value or "").strip().lower()
        return normalized in {"1", "true", "ja", "yes", "y"}
