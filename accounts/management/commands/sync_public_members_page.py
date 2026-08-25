import glob
import ipaddress
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError

from accounts.public_members import build_public_members_payload


def _is_private_or_local_host(hostname):
    if not hostname:
        return True

    host = hostname.strip().strip("[]").lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        return True

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False

    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_unspecified,
            ip.is_reserved,
            ip.is_multicast,
        )
    )


def validate_public_member_media_urls(allow_private_media_host=False):
    payload = build_public_members_payload()
    invalid_urls = []

    for section in payload.get("sections", {}).values():
        for member in section.get("members", []):
            photo = member.get("photo") or {}
            for variant in photo.get("variants", {}).values():
                url = (variant.get("url") or "").strip()
                if not url:
                    continue

                parsed = urlparse(url)
                scheme = (parsed.scheme or "").lower()
                hostname = parsed.hostname or ""

                if scheme != "https":
                    invalid_urls.append((member.get("display_name") or "", url, "not_https"))
                    continue

                if not allow_private_media_host and _is_private_or_local_host(hostname):
                    invalid_urls.append((member.get("display_name") or "", url, "private_host"))

    return invalid_urls


class Command(BaseCommand):
    help = "Konfiguriert WordPress für die öffentliche Mitglieder-API, ohne das Elementor-Layout zu überschreiben."

    def add_arguments(self, parser):
        parser.add_argument(
            "--site-url",
            default="http://127.0.0.1:8000",
            help="Absolute Basis-URL des Django-Servers, aus der /api/v1/public/ gebildet wird.",
        )
        parser.add_argument(
            "--php-binary",
            default="",
            help="Optionaler Pfad zur verwendeten php.exe.",
        )
        parser.add_argument(
            "--phprc",
            default="",
            help="Optionaler Pfad zum PHPRC-Verzeichnis der Local-WordPress-Installation.",
        )
        parser.add_argument(
            "--allow-private-media-host",
            action="store_true",
            help="Erlaubt ausnahmsweise Profilbild-URLs mit localhost-, .local- oder privaten IP-Hosts.",
        )

    def handle(self, *args, **options):
        app_root = Path(__file__).resolve().parents[4]
        sync_script = app_root / "intern" / "tools" / "wordpress" / "sync_members_page.php"
        if not sync_script.exists():
            raise CommandError(f"WordPress-Sync-Skript fehlt: {sync_script}")

        site_url = options["site_url"].rstrip("/")
        api_base = f"{site_url}/api/v1/public/"
        invalid_media_urls = validate_public_member_media_urls(
            allow_private_media_host=options["allow_private_media_host"]
        )

        if invalid_media_urls:
            details = "\n".join(
                f"- {member or 'Unbekannt'}: {url} ({reason})"
                for member, url, reason in invalid_media_urls[:10]
            )
            raise CommandError(
                "WordPress-Sync abgebrochen: Die öffentlichen Mitgliederbilder verweisen nicht auf eine "
                "robuste externe HTTPS-URL.\n"
                "Setze PUBLIC_MEDIA_BASE_URL auf die spätere Django-Instanz wie "
                "https://intern.avfroburger.ch/media/ und erzeuge den Snapshot danach neu.\n"
                "Gefundene problematische URLs:\n"
                f"{details}"
            )

        php_binary = options["php_binary"] or self._detect_local_php_binary()
        phprc = options["phprc"] or self._detect_local_phprc()

        env = os.environ.copy()
        if phprc:
            env["PHPRC"] = phprc

        completed = subprocess.run(
            [php_binary, str(sync_script), api_base],
            cwd=app_root,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            details = stderr or stdout or "Unbekannter PHP-Fehler."
            raise CommandError(f"WordPress-Sync fehlgeschlagen: {details}")

        self.stdout.write(self.style.SUCCESS("Öffentliche Mitglieder-API in WordPress konfiguriert."))
        if completed.stdout.strip():
            self.stdout.write(completed.stdout.strip())

    def _detect_local_php_binary(self):
        roots = [
            Path.home() / "AppData" / "Roaming" / "Local" / "lightning-services",
            Path.home() / "AppData" / "Local" / "Programs" / "Local" / "resources" / "extraResources" / "lightning-services",
        ]
        candidates = []
        for root in roots:
            candidates.extend(root.glob("php-*/bin/win64/php.exe"))
        candidates = sorted({candidate.resolve() for candidate in candidates}, reverse=True)
        if not candidates:
            raise CommandError(
                "php.exe wurde nicht gefunden. Bitte --php-binary angeben oder Local PHP installieren."
            )
        return str(candidates[0])

    def _detect_local_phprc(self):
        run_root = Path.home() / "AppData" / "Roaming" / "Local" / "run"
        candidates = sorted(glob.glob(str(run_root / "*" / "conf" / "php")), reverse=True)
        return candidates[0] if candidates else ""
