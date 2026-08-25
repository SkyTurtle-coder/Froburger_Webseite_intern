import getpass
import os
import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import Role
from accounts.roles import ROLE_CHOICES

# SEC-014: no --password CLI flag. Command-line arguments are visible to any
# other process on the same host (`ps aux`) and get written to shell
# history - unacceptable for a credential, even for a one-time provisioning
# command. Scripted/non-interactive deployments should set this environment
# variable (e.g. from a deploy-time secret store); anyone running the
# command by hand gets prompted with getpass instead (no echo).
PASSWORD_ENV_VAR = "AVF_BOOTSTRAP_ADMIN_PASSWORD"


class Command(BaseCommand):
    help = "Legt Rollen und optional einen initialen Admin-Benutzer an."

    def add_arguments(self, parser):
        parser.add_argument("--email", type=str, default="", help="E-Mail des initialen Admins")
        parser.add_argument("--first-name", type=str, default="Admin", help="Vorname des initialen Admins")
        parser.add_argument("--last-name", type=str, default="Benutzer", help="Nachname des initialen Admins")
        parser.add_argument("--vulgo", type=str, default="", help="Vulgo des initialen Admins")

    def _resolve_password(self):
        password = os.environ.get(PASSWORD_ENV_VAR)
        if password:
            return password
        return getpass.getpass("Passwort für den initialen Admin: ")

    def handle(self, *args, **options):
        for code, _label in ROLE_CHOICES:
            Role.objects.get_or_create(code=code)
        self.stdout.write(self.style.SUCCESS("Rollen sichergestellt."))

        email = options["email"].strip()
        if not email:
            self.stdout.write("Kein Admin-Benutzer angefordert.")
            return

        password = self._resolve_password()
        if not password:
            raise SystemExit(
                f"Ein Passwort ist erforderlich: entweder {PASSWORD_ENV_VAR} setzen oder interaktiv eingeben."
            )

        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first()
        created = user is None
        if created:
            user = User(
                username=f"mitglied-{secrets.token_hex(16)}",
                email=email,
                is_staff=True,
                is_superuser=True,
            )

        if created:
            user.set_password(password)
        else:
            user.email = email
            user.is_staff = True
            user.is_superuser = True
            if password:
                user.set_password(password)
        user.save()

        profile = user.profile
        profile.first_name = options["first_name"]
        profile.last_name = options["last_name"]
        profile.vulgo = options["vulgo"]
        profile.save()
        profile.roles.set(Role.objects.filter(code="ADMIN"))

        self.stdout.write(self.style.SUCCESS(f"Admin-Benutzer für {email} bereit."))
