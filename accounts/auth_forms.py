from django import forms
from django.contrib.auth.forms import AuthenticationForm

from . import throttling
from .auth_backends import EmailOrVulgoBackend


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

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        identifier = EmailOrVulgoBackend.normalize_identifier(username)

        if username is not None and password:
            if throttling.is_throttled(self.request, identifier):
                # Same generic error as any other failed login (SEC-002): a
                # throttled attempt must be indistinguishable from a wrong
                # password, so it gives an attacker no extra signal and no
                # existing test/UI copy needs to change.
                raise self.get_invalid_login_error()

        try:
            cleaned_data = super().clean()
        except forms.ValidationError:
            throttling.register_failed_attempt(self.request, identifier)
            raise

        if self.get_user() is not None:
            throttling.clear_attempts_for_identifier(identifier)
        return cleaned_data
