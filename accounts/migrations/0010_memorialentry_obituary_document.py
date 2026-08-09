from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0002_document_folder_optional"),
        ("accounts", "0009_alter_memorialentry_import_key_nullable"),
    ]

    operations = [
        migrations.AddField(
            model_name="memorialentry",
            name="obituary_document",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="memorial_entries",
                to="documents.document",
                verbose_name="Nachruf",
            ),
        ),
    ]
