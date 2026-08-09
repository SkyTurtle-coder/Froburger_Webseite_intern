import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from accounts.models import Profile
from accounts.public_members import is_public_member


class Command(BaseCommand):
    """SEC-006: sweeps MEDIA_ROOT/public/members/<pk>/ for derivative photo
    directories that no longer belong to a publicly-listed profile (deceased,
    lost their public role, or the profile was deleted outright) and removes
    them. The normal path (accounts/services.py::sync_profile_side_effects,
    via transaction.on_commit) already does this the moment a profile's
    status changes, so this command exists for the cases that predate that
    fix, or a manual re-sweep after a bulk data import. Never touches the
    original Profile.photo upload - only the generated public/ derivatives.
    """

    help = "Removes cached public member-photo derivatives for profiles that are no longer publicly listed."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without deleting anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        public_members_root = Path(settings.MEDIA_ROOT) / "public" / "members"

        if not public_members_root.exists():
            self.stdout.write("No public member media directory found - nothing to do.")
            return

        public_profile_ids = {profile.pk for profile in Profile.objects.all() if is_public_member(profile)}

        removed = 0
        kept = 0
        for entry in sorted(public_members_root.iterdir()):
            if not entry.is_dir():
                continue

            try:
                profile_pk = int(entry.name)
            except ValueError:
                # Not a profile-id-named directory - leave it alone, it's not ours to judge.
                continue

            if profile_pk in public_profile_ids:
                kept += 1
                continue

            removed += 1
            if dry_run:
                self.stdout.write(f"[dry-run] would remove: profile_id={profile_pk} path={entry}")
            else:
                shutil.rmtree(entry, ignore_errors=True)
                self.stdout.write(f"removed: profile_id={profile_pk}")

        verb = "Would remove" if dry_run else "Removed"
        self.stdout.write(self.style.SUCCESS(f"{verb} {removed} stale director(y/ies), kept {kept} public one(s)."))
