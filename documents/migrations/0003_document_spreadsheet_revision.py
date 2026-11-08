from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("documents", "0002_document_folder_optional")]

    operations = [
        migrations.AddField(
            model_name="document",
            name="spreadsheet_revision",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="SpreadsheetRevision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("revision", models.PositiveIntegerField()),
                ("file", models.FileField(upload_to="protected/spreadsheet-revisions/")),
                ("saved_at", models.DateTimeField(auto_now_add=True)),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="spreadsheet_revisions", to="documents.document")),
                ("saved_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-revision"]},
        ),
        migrations.AddConstraint(
            model_name="spreadsheetrevision",
            constraint=models.UniqueConstraint(fields=("document", "revision"), name="unique_document_spreadsheet_revision"),
        ),
    ]
