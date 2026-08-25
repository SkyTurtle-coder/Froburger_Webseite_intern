import csv
import io
import secrets
import unicodedata
from dataclasses import dataclass, field

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from . import public_media
from .models import MemorialEntry, Profile, Role
from .public_members import is_public_member


@dataclass
class MemberImportRowIssue:
    row_number: int
    reason: str
    email: str = ""
    display_name: str = ""


@dataclass
class MemberImportResult:
    created_count: int = 0
    updated_count: int = 0
    skipped_duplicates: list[MemberImportRowIssue] = field(default_factory=list)
    skipped_invalid: list[MemberImportRowIssue] = field(default_factory=list)


CSV_HEADER_ALIASES = {
    "first_name": {"vorname", "vornamen", "firstname", "first_name"},
    "last_name": {"name", "namen", "nachname", "lastname", "last_name"},
    "vulgo": {"vulgo", "vulo", "vo", "v/o", "v o", "v_o"},
    "email": {"email", "e-mail", "mail", "emailadresse", "email_address"},
    "status": {"status", "mitgliedstatus", "mitgliederstatus", "stand"},
}

CSV_STATUS_ROLE_CODES = {
    "aktivitas": None,
    "altfroburger": "ALTFROBURGER",
    "ehrenphilister": "EHRENPHILISTER",
}


def _normalize_import_value(value):
    normalized = unicodedata.normalize("NFKC", (value or "").strip())
    return " ".join(normalized.split())


def _normalize_import_key(*parts):
    return tuple(_normalize_import_value(part).casefold() for part in parts)


def _normalize_import_status(value):
    normalized = _normalize_import_value(value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _decode_csv_bytes(raw_bytes):
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Die CSV-Datei konnte nicht gelesen werden. Bitte als UTF-8 oder CSV aus Excel exportieren.")


def _csv_dialect(sample):
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t")
    except csv.Error:
        return csv.excel


def _resolve_csv_headers(fieldnames):
    header_map = {}
    normalized_headers = {_normalize_import_value(name).casefold(): name for name in fieldnames if name}
    missing_fields = []
    for target, aliases in CSV_HEADER_ALIASES.items():
        match = next((normalized_headers[alias] for alias in aliases if alias in normalized_headers), None)
        if match is None:
            missing_fields.append(target)
            continue
        header_map[target] = match
    if missing_fields:
        raise ValueError(
            "Die CSV braucht Spalten für Name, Vorname, Vulgo, E-Mail-Adresse und Status."
        )
    return header_map


def _generate_internal_username():
    while True:
        username = f"mitglied-{secrets.token_hex(16)}"
        if not User.objects.filter(username=username).exists():
            return username


def import_members_from_csv(uploaded_file):
    raw_bytes = uploaded_file.read()
    uploaded_file.seek(0)
    content = _decode_csv_bytes(raw_bytes)
    reader = csv.DictReader(io.StringIO(content), dialect=_csv_dialect(content[:2048]))
    if not reader.fieldnames:
        raise ValueError("Die CSV-Datei enthält keine Spaltenüberschriften.")

    header_map = _resolve_csv_headers(reader.fieldnames)
    result = MemberImportResult()

    existing_profiles = list(Profile.objects.select_related("user").prefetch_related("roles"))
    existing_email_profiles = {
        _normalize_import_value(profile.user.email).casefold(): profile
        for profile in existing_profiles
        if _normalize_import_value(profile.user.email)
    }
    existing_profile_keys = {
        _normalize_import_key(profile.first_name, profile.last_name, profile.vulgo): profile
        for profile in existing_profiles
    }
    roles_by_code = {role.code: role for role in Role.objects.filter(code__in=CSV_STATUS_ROLE_CODES.values()) if role.code}

    for row_index, row in enumerate(reader, start=2):
        first_name = _normalize_import_value(row.get(header_map["first_name"]))
        last_name = _normalize_import_value(row.get(header_map["last_name"]))
        vulgo = _normalize_import_value(row.get(header_map["vulgo"]))
        email = _normalize_import_value(row.get(header_map["email"])).lower()
        status = _normalize_import_status(row.get(header_map["status"]))
        display_name = " ".join(part for part in (first_name, last_name) if part)

        if not first_name or not last_name or not email:
            result.skipped_invalid.append(
                MemberImportRowIssue(
                    row_number=row_index,
                    reason="Pflichtfeld fehlt",
                    email=email,
                    display_name=display_name,
                )
            )
            continue

        if status not in CSV_STATUS_ROLE_CODES:
            result.skipped_invalid.append(
                MemberImportRowIssue(
                    row_number=row_index,
                    reason="Unbekannter Status",
                    email=email,
                    display_name=display_name,
                )
            )
            continue

        try:
            validate_email(email)
        except ValidationError:
            result.skipped_invalid.append(
                MemberImportRowIssue(
                    row_number=row_index,
                    reason="Ungültige E-Mail-Adresse",
                    email=email,
                    display_name=display_name,
                )
            )
            continue

        email_key = email.casefold()
        profile_key = _normalize_import_key(first_name, last_name, vulgo)
        matched_profiles = {
            profile.pk: profile
            for profile in (existing_email_profiles.get(email_key), existing_profile_keys.get(profile_key))
            if profile is not None
        }
        if len(matched_profiles) > 1:
            result.skipped_invalid.append(
                MemberImportRowIssue(
                    row_number=row_index,
                    reason="E-Mail und Name gehören zu unterschiedlichen Mitgliedern",
                    email=email,
                    display_name=display_name,
                )
            )
            continue

        if matched_profiles:
            profile = next(iter(matched_profiles.values()))
            role_code = CSV_STATUS_ROLE_CODES[status]
            existing_role_codes = {role.code for role in profile.roles.all()}
            if role_code and role_code not in existing_role_codes:
                with transaction.atomic():
                    profile.roles.add(roles_by_code[role_code])
                result.updated_count += 1
                continue

            result.skipped_duplicates.append(
                MemberImportRowIssue(
                    row_number=row_index,
                    reason="Bereits vorhanden",
                    email=email,
                    display_name=display_name,
                )
            )
            continue

        with transaction.atomic():
            user = User.objects.create_user(
                username=_generate_internal_username(),
                email=email,
                first_name=first_name,
                last_name=last_name,
            )
            user.set_unusable_password()
            user.save(update_fields=["password"])

            profile = user.profile
            profile.first_name = first_name
            profile.last_name = last_name
            profile.vulgo = vulgo
            profile.full_clean()
            profile.save()

            role_code = CSV_STATUS_ROLE_CODES[status]
            if role_code:
                profile.roles.add(Role.objects.get(code=role_code))

        existing_email_profiles[email_key] = profile
        existing_profile_keys[profile_key] = profile
        result.created_count += 1

    return result


def sync_profile_membership_state(profile):
    if profile.death_date and profile.user.is_active:
        User.objects.filter(pk=profile.user_id, is_active=True).update(is_active=False)
        profile.user.is_active = False


def sync_profile_memorial_entry(profile):
    generated_entry = (
        MemorialEntry.objects.select_for_update()
        .filter(member_profile=profile, is_profile_generated=True)
        .first()
    )
    if not profile.death_date:
        if generated_entry and generated_entry.is_published:
            generated_entry.is_published = False
            generated_entry.save(update_fields=["is_published", "updated_at"])
        return

    defaults = {
        "display_name": profile.memorial_display_name,
        "birth_date": profile.birth_date,
        "birth_date_display": "",
        "death_date": profile.death_date,
        "death_date_display": "",
        "sort_date": profile.death_date,
        "is_published": True,
        "is_profile_generated": True,
        "import_key": "",
    }
    if generated_entry:
        for field_name, value in defaults.items():
            setattr(generated_entry, field_name, value)
        generated_entry.full_clean()
        generated_entry.save()
        return

    generated_entry = MemorialEntry(member_profile=profile, **defaults)
    generated_entry.full_clean()
    generated_entry.save()


def sync_profile_side_effects(profile):
    with transaction.atomic():
        sync_profile_membership_state(profile)
        sync_profile_memorial_entry(profile)

    # SEC-006: file deletion can't be rolled back, so it must only run once
    # the DB state above is actually committed - never inside the atomic
    # block. Removes cached public photo derivatives once a profile stops
    # being publicly listed (deceased / lost its public role), using the
    # exact same is_public_member() policy the public members API itself
    # uses, so the two can never disagree about who counts as public.
    transaction.on_commit(lambda: _purge_media_if_no_longer_public(profile))


def _purge_media_if_no_longer_public(profile):
    if not is_public_member(profile) or profile.avatar_icon in Profile.AvatarIcon.values:
        public_media.purge_public_member_media(profile.pk)


def memorial_queryset():
    return (
        MemorialEntry.objects.filter(is_published=True)
        .select_related("member_profile", "member_profile__user")
        .order_by("-death_date", "-sort_date", "-pk")
    )
