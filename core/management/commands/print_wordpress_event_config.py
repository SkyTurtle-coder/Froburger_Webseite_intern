from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Gibt die empfohlenen WordPress-Plugin-Optionen für die Event-API aus."

    def handle(self, *args, **options):
        source_base = settings.PUBLIC_EVENT_SOURCE_BASE_URL.rstrip("/")
        page_path = f"/{settings.PUBLIC_EVENT_DETAIL_PATH_PREFIX.strip('/')}/"
        if source_base:
            legacy = f"{source_base}/api/public/events/upcoming/"
            v1 = f"{source_base}/api/v1/public/"
        else:
            legacy = "SET PUBLIC_EVENT_SOURCE_BASE_URL FIRST"
            v1 = "SET PUBLIC_EVENT_SOURCE_BASE_URL FIRST"

        self.stdout.write("Recommended WordPress Event Settings")
        self.stdout.write(f"API endpoint: {legacy}")
        self.stdout.write(f"API base v1: {v1}")
        self.stdout.write(f"Page path: {page_path}")
