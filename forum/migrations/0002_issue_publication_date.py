from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def preserve_publication_dates(apps, schema_editor):
    Issue = apps.get_model("forum", "Issue")
    zone = ZoneInfo(settings.TIME_ZONE)
    issues = Issue.objects.using(schema_editor.connection.alias)
    for issue in issues.all().iterator():
        created = issue.created_at
        date = timezone.localtime(created, zone).date() if timezone.is_aware(created) else created.date()
        issues.filter(pk=issue.pk).update(publication_date=date)


class Migration(migrations.Migration):
    dependencies = [("forum", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="issue", name="publication_date",
            field=models.DateField("Veröffentlichungsdatum", null=True, db_index=True),
        ),
        migrations.RunPython(preserve_publication_dates, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="issue", name="publication_date",
            field=models.DateField("Veröffentlichungsdatum", default=timezone.localdate, db_index=True),
        ),
        migrations.AlterModelOptions(
            name="issue", options={"ordering": ["-publication_date", "-pk"],
                "verbose_name": "Forum-Ausgabe", "verbose_name_plural": "Forum-Ausgaben"},
        ),
    ]
