from django import forms
from django.contrib.auth.forms import AuthenticationForm


class VulgoAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="E-Mail oder Vulgo",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "autofocus": True,
                "autocomplete": "username",
                "placeholder": "Deine E-Mail oder dein Vulgo",
            }
        ),
    )

    error_messages = {
        "invalid_login": "Anmeldung fehlgeschlagen. Bitte prüfe E-Mail oder Vulgo und Passwort.",
        "inactive": "Anmeldung fehlgeschlagen. Bitte prüfe E-Mail oder Vulgo und Passwort.",
    }
