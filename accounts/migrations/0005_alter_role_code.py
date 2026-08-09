from django.db import migrations, models

from accounts.roles import ROLE_CHOICES


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_calendarsubscription"),
    ]

    operations = [
        migrations.AlterField(
            model_name="role",
            name="code",
            field=models.CharField(choices=ROLE_CHOICES, max_length=32, unique=True),
        ),
    ]
