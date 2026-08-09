from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Event",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("start", models.DateTimeField()),
                ("end", models.DateTimeField()),
                ("location", models.CharField(blank=True, max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("INTERN", "Intern"),
                            ("OFF", "Off"),
                            ("INOFF", "Inoff"),
                            ("IAOFF", "Iaoff"),
                            ("HOCHOFF", "Hochoff"),
                        ],
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["start", "title"]},
        ),
    ]
