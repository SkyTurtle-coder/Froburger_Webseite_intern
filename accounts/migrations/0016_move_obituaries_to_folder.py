from django.db import migrations


OBITUARY_FOLDER_NAME = "Nachrufe"
GENERAL_SCOPE = "GENERAL"


def move_obituaries_to_folder(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    DocumentFolder = apps.get_model("documents", "DocumentFolder")
    MemorialEntry = apps.get_model("accounts", "MemorialEntry")

    folder, _created = DocumentFolder.objects.get_or_create(
        name=OBITUARY_FOLDER_NAME,
        scope=GENERAL_SCOPE,
        parent=None,
    )
    obituary_document_ids = MemorialEntry.objects.exclude(obituary_document_id__isnull=True).values_list(
        "obituary_document_id",
        flat=True,
    )
    Document.objects.filter(pk__in=obituary_document_ids).update(
        folder_id=folder.pk,
        visibility=GENERAL_SCOPE,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0015_anonymize_usernames"),
        ("documents", "0002_document_folder_optional"),
    ]

    operations = [
        migrations.RunPython(move_obituaries_to_folder, migrations.RunPython.noop),
    ]
