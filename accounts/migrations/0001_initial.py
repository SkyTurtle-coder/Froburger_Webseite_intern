from django.db import migrations, models
import django.db.models.deletion


ROLE_CHOICES = [
    ("SENIOR", "Senior"),
    ("CONSENIOR", "Consenior"),
    ("FUXMAJOR", "Fuxmajor"),
    ("AKTUAR", "Aktuar"),
    ("QUAESTOR", "Quästor"),
    ("FUX", "Fux"),
    ("BURSCH", "Bursch"),
    ("WEB_X", "Web-X"),
    ("ADMIN", "Admin"),
]


def create_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for code, _label in ROLE_CHOICES:
        Role.objects.get_or_create(code=code)


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="Role",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(choices=ROLE_CHOICES, max_length=32, unique=True)),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="Profile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("photo", models.ImageField(blank=True, upload_to="avatars/")),
                ("first_name", models.CharField(max_length=150)),
                ("last_name", models.CharField(max_length=150)),
                ("vulgo", models.CharField(blank=True, max_length=150)),
                ("roles", models.ManyToManyField(blank=True, related_name="profiles", to="accounts.role")),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="profile",
                        to="auth.user",
                    ),
                ),
            ],
            options={"ordering": ["last_name", "first_name"]},
        ),
        migrations.RunPython(create_roles, migrations.RunPython.noop),
    ]
