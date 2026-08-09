from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentFolder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150)),
                ("scope", models.CharField(choices=[("GENERAL", "Allgemein"), ("SENSITIVE", "Sensibel")], max_length=16)),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="children",
                        to="documents.documentfolder",
                    ),
                ),
            ],
            options={"ordering": ["scope", "name"], "unique_together": {("scope", "parent", "name")}},
        ),
        migrations.CreateModel(
            name="Document",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("visibility", models.CharField(choices=[("GENERAL", "Allgemein"), ("SENSITIVE", "Sensibel")], max_length=16)),
                ("file", models.FileField(upload_to="protected/")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "folder",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="documents",
                        to="documents.documentfolder",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="uploaded_documents",
                        to="auth.user",
                    ),
                ),
            ],
            options={"ordering": ["folder__name", "title"]},
        ),
    ]
