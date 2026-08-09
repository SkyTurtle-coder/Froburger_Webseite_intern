from django.contrib.auth.models import User
from django.db import transaction

from . import public_media
from .models import MemorialEntry
from .public_members import is_public_member


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
    if not is_public_member(profile):
        public_media.purge_public_member_media(profile.pk)


def memorial_queryset():
    return (
        MemorialEntry.objects.filter(is_published=True)
        .select_related("member_profile", "member_profile__user")
        .order_by("-death_date", "-sort_date", "-pk")
    )
