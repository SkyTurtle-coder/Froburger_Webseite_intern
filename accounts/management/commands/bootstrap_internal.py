from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import Role
from accounts.roles import ROLE_CHOICES


class Command(BaseCommand):
    help = "Legt Rollen und optional einen initialen Admin-Benutzer an."

    def add_arguments(self, parser):
        parser.add_argument("--username", type=str, help="Benutzername des initialen Admins")
        parser.add_argument("--password", type=str, help="Passwort des initialen Admins")
        parser.add_argument("--email", type=str, default="", help="E-Mail des initialen Admins")
        parser.add_argument("--first-name", type=str, default="Admin", help="Vorname des initialen Admins")
        parser.add_argument("--last-name", type=str, default="Benutzer", help="Nachname des initialen Admins")
        parser.add_argument("--vulgo", type=str, default="", help="Vulgo des initialen Admins")

    def handle(self, *args, **options):
        for code, _label in ROLE_CHOICES:
            Role.objects.get_or_create(code=code)
        self.stdout.write(self.style.SUCCESS("Rollen sichergestellt."))

        username = options.get("username")
        password = options.get("password")
        if not username:
            self.stdout.write("Kein Admin-Benutzer angefordert.")
            return
        if not password:
            raise SystemExit("Wenn --username gesetzt ist, muss auch --password gesetzt werden.")

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": options["email"],
                "is_staff": True,
                "is_superuser": True,
            },
        )

        if created:
            user.set_password(password)
        else:
            user.email = options["email"] or user.email
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

        self.stdout.write(self.style.SUCCESS(f"Admin-Benutzer '{username}' bereit."))
