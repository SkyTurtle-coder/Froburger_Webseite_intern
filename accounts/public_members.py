import hashlib
import json

from django.utils import timezone

from .models import Profile
from .public_media import build_public_member_photo
from .roles import ROLE_LABELS


PUBLIC_MEMBERS_SCHEMA_VERSION = 2

PUBLIC_COMMITTEE_ROLE_CODES = (
    "SENIOR",
    "CONSENIOR",
    "FUXMAJOR",
    "AKTUAR",
    "QUAESTOR",
)

PUBLIC_SECTION_DEFINITIONS = (
    ("committee", "Komitee", PUBLIC_COMMITTEE_ROLE_CODES),
    ("salon", "Der Salon", ("BURSCH",)),
    ("stall", "Der Stall", ("FUX",)),
    ("altfroburger", "Altfroburger", ("ALTFROBURGER",)),
    ("af_committee", "Das Altfroburger-Komitee", ("AF_PRAESIDENT", "AF_AKTUAR", "AF_KASSIER")),
)

PUBLIC_ROLE_SORT_ORDER = {
    "SENIOR": 10,
    "CONSENIOR": 20,
    "FUXMAJOR": 30,
    "AKTUAR": 40,
    "QUAESTOR": 50,
    "BURSCH": 100,
    "FUX": 110,
    "ALTFROBURGER": 120,
    "AF_PRAESIDENT": 130,
    "AF_AKTUAR": 140,
    "AF_KASSIER": 150,
}

PUBLIC_SECTION_CONFIG = {
    section_key: {
        "title": section_title,
        "role_codes": tuple(section_role_codes),
    }
    for section_key, section_title, section_role_codes in PUBLIC_SECTION_DEFINITIONS
}

PUBLIC_ROLE_TO_SECTIONS = {}
for section_key, section_config in PUBLIC_SECTION_CONFIG.items():
    for role_code in section_config["role_codes"]:
        PUBLIC_ROLE_TO_SECTIONS.setdefault(role_code, []).append(section_key)


def is_public_member(profile):
    """Single source of truth for "does this profile appear in the public
    member directory". Also used by the SEC-006 media-lifecycle cleanup
    (accounts/services.py) so the two can never diverge on who counts as
    public - a profile that build_public_members_payload() would exclude
    must always be exactly the profiles whose cached public photo
    derivatives get purged.
    """
    if profile.is_deceased:
        return False
    return bool(_collect_public_roles_by_section(profile))


def build_public_members_payload():
    profiles = list(
        Profile.objects.select_related("user")
        .prefetch_related("roles")
        .order_by("last_name", "first_name", "pk")
    )

    sections = {
        section_key: {
            "title": section_config["title"],
            "count": 0,
            "members": [],
        }
        for section_key, section_config in PUBLIC_SECTION_CONFIG.items()
    }
    public_member_ids = set()

    for profile in profiles:
        if not is_public_member(profile):
            continue

        roles_by_section = _collect_public_roles_by_section(profile)

        public_member_ids.add(profile.pk)

        for section_key, public_roles in roles_by_section.items():
            sections[section_key]["members"].append(_member_payload(profile, public_roles))

    for section in sections.values():
        section["members"].sort(key=_member_sort_key)
        section["count"] = len(section["members"])

    normalized = {
        "schema_version": PUBLIC_MEMBERS_SCHEMA_VERSION,
        "generated_at": timezone.now().isoformat(),
        "member_count": len(public_member_ids),
        "section_order": [section_key for section_key, _, _ in PUBLIC_SECTION_DEFINITIONS],
        "sections": sections,
    }
    normalized["content_hash"] = _content_hash(normalized)
    return normalized


def _collect_public_roles_by_section(profile):
    roles_by_section = {}
    for role in profile.roles.all():
        target_sections = PUBLIC_ROLE_TO_SECTIONS.get(role.code, ())
        if not target_sections:
            continue

        public_role = {
            "key": role.code.lower(),
            "code": role.code,
            "label": ROLE_LABELS.get(role.code, role.code),
            "sort_order": PUBLIC_ROLE_SORT_ORDER.get(role.code, 999),
        }
        for section_key in target_sections:
            roles_by_section.setdefault(section_key, []).append(public_role)

    for section_roles in roles_by_section.values():
        section_roles.sort(key=lambda role: (role["sort_order"], role["label"], role["code"]))

    return roles_by_section


def _member_payload(profile, public_roles):
    display_name = f"{profile.first_name} {profile.last_name}".strip()
    photo = build_public_member_photo(profile)
    entry_display = profile.entry_term_display

    return {
        "id": profile.pk,
        "display_name": display_name,
        "name": display_name,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "vulgo": profile.vulgo,
        "entry_year": profile.entry_year,
        "entry_semester": profile.entry_semester,
        "entry_display": entry_display,
        "academic_title": profile.academic_title,
        "degree_program": profile.degree_program,
        "roles": [
            {
                "key": role["key"],
                "label": role["label"],
                "sort_order": role["sort_order"],
            }
            for role in public_roles
        ],
        "photo": photo,
    }


def _member_sort_key(member):
    first_role = member["roles"][0] if member["roles"] else {"sort_order": 999}
    return (
        first_role["sort_order"],
        member["last_name"].casefold(),
        member["first_name"].casefold(),
        member["id"],
    )


def _content_hash(payload):
    sections = {}
    for section_key in payload["section_order"]:
        section = payload["sections"][section_key]
        sections[section_key] = {
            "title": section["title"],
            "count": section["count"],
            "members": [
                {
                    "id": member["id"],
                    "display_name": member["display_name"],
                    "first_name": member["first_name"],
                    "last_name": member["last_name"],
                    "vulgo": member["vulgo"],
                    "entry_year": member["entry_year"],
                    "entry_semester": member["entry_semester"],
                    "entry_display": member["entry_display"],
                    "academic_title": member["academic_title"],
                    "degree_program": member["degree_program"],
                    "roles": member["roles"],
                    "photo": {
                        "fallback": member["photo"]["fallback"],
                        "variants": member["photo"]["variants"] if member["photo"]["variants"] else [],
                    },
                }
                for member in section["members"]
            ],
        }

    payload_for_hash = {
        "schema_version": payload["schema_version"],
        "member_count": payload["member_count"],
        "section_order": payload["section_order"],
        "sections": sections,
    }
    raw = json.dumps(payload_for_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
