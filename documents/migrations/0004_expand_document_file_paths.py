from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0003_document_spreadsheet_revision"),
    ]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="file",
            field=models.FileField(max_length=255, upload_to="protected/"),
        ),
        migrations.AlterField(
            model_name="spreadsheetrevision",
            name="file",
            field=models.FileField(max_length=255, upload_to="protected/spreadsheet-revisions/"),
        ),
    ]
