from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_alter_role_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="academic_title",
            field=models.CharField(blank=True, max_length=150, verbose_name="Abschluss / Titel"),
        ),
        migrations.AddField(
            model_name="profile",
            name="birth_date",
            field=models.DateField(blank=True, null=True, verbose_name="Geburtsdatum"),
        ),
        migrations.AddField(
            model_name="profile",
            name="death_date",
            field=models.DateField(blank=True, null=True, verbose_name="Todesdatum"),
        ),
        migrations.AddField(
            model_name="profile",
            name="degree_program",
            field=models.CharField(blank=True, max_length=255, verbose_name="Studiengang"),
        ),
        migrations.AddField(
            model_name="profile",
            name="entry_semester",
            field=models.CharField(blank=True, choices=[("FS", "FS"), ("HS", "HS")], max_length=2, verbose_name="Eintrittssemester"),
        ),
        migrations.AddField(
            model_name="profile",
            name="entry_year",
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="Eintrittsjahr"),
        ),
        migrations.AddField(
            model_name="profile",
            name="exit_semester",
            field=models.CharField(blank=True, choices=[("FS", "FS"), ("HS", "HS")], max_length=2, verbose_name="Austrittssemester"),
        ),
        migrations.AddField(
            model_name="profile",
            name="exit_year",
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="Austrittsjahr"),
        ),
        migrations.CreateModel(
            name="MemorialEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(max_length=255, verbose_name="Anzeigename")),
                ("birth_date", models.DateField(blank=True, null=True, verbose_name="Geburtsdatum")),
                ("birth_date_display", models.CharField(blank=True, max_length=80, verbose_name="Geburtsdatum Anzeige")),
                ("death_date", models.DateField(blank=True, null=True, verbose_name="Todesdatum")),
                ("death_date_display", models.CharField(blank=True, max_length=80, verbose_name="Todesdatum Anzeige")),
                ("sort_date", models.DateField(blank=True, null=True, verbose_name="Sortierdatum")),
                ("sort_order", models.PositiveIntegerField(default=0, verbose_name="Manuelle Sortierung")),
                ("is_published", models.BooleanField(default=False, verbose_name="Veröffentlicht")),
                ("is_honorary_member", models.BooleanField(default=False, verbose_name="Ehrenphilister")),
                ("legacy_marker", models.CharField(blank=True, max_length=16, verbose_name="Legacy-Markierung")),
                ("is_profile_generated", models.BooleanField(default=False, editable=False, verbose_name="Automatisch aus Profil erzeugt")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "member_profile",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="memorial_entries",
                        to="accounts.profile",
                        verbose_name="Mitgliederprofil",
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order", "pk"],
            },
        ),
        migrations.AddConstraint(
            model_name="memorialentry",
            constraint=models.UniqueConstraint(
                condition=Q(is_profile_generated=True),
                fields=("member_profile",),
                name="accounts_memorialentry_unique_generated_profile",
            ),
        ),
    ]
