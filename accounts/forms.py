from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import User
from django.db import transaction
from django.utils.crypto import get_random_string

from . import throttling
from .models import MemorialEntry, Profile, Role


MAX_OBITUARY_FILE_SIZE = 20 * 1024 * 1024
MAX_MEMBER_CSV_FILE_SIZE = 5 * 1024 * 1024
MAX_PROFILE_PHOTO_FILE_SIZE = 20 * 1024 * 1024
MAX_PROFILE_PHOTO_PIXELS = 40_000_000
ISO_DATE_INPUT_FORMAT = "%Y-%m-%d"


def html5_date_input():
    return forms.DateInput(format=ISO_DATE_INPUT_FORMAT, attrs={"type": "date"})


def validate_profile_photo(upload):
    """Apply resource limits after Django/Pillow has verified the image."""
    if not upload or getattr(upload, "_committed", False):
        return upload
    if upload.size > MAX_PROFILE_PHOTO_FILE_SIZE:
        raise forms.ValidationError("Das Profilfoto darf höchstens 20 MB gross sein.")

    image = getattr(upload, "image", None)
    width = getattr(image, "width", 0) or 0
    height = getattr(image, "height", 0) or 0
    if width * height > MAX_PROFILE_PHOTO_PIXELS:
        raise forms.ValidationError("Das Profilfoto hat zu viele Bildpunkte.")
    return upload


class RoleMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return obj.display_label


class MemberCsvImportForm(forms.Form):
    csv_file = forms.FileField(
        label="CSV-Datei",
        help_text="Erwartete Spalten: Name, Vorname, Vulgo, E-Mail-Adresse und Status. Status: Aktivitas, Alt-Froburger oder Ehrenphilister.",
    )

    def clean_csv_file(self):
        uploaded_file = self.cleaned_data["csv_file"]
        if uploaded_file.size > MAX_MEMBER_CSV_FILE_SIZE:
            raise forms.ValidationError("Die CSV-Datei darf höchstens 5 MB gross sein.")
        file_name = (uploaded_file.name or "").lower()
        if not file_name.endswith(".csv"):
            raise forms.ValidationError("Bitte eine CSV-Datei hochladen.")
        return uploaded_file


class ProfileBaseForm(forms.ModelForm):
    email = forms.EmailField(
        label="E-Mail-Adresse",
        max_length=254,
        help_text="Diese Adresse wird für die Anmeldung und das Zurücksetzen des Passworts verwendet.",
    )
    birth_date = forms.DateField(
        label="Geburtsdatum",
        required=False,
        input_formats=[ISO_DATE_INPUT_FORMAT],
        widget=html5_date_input(),
    )
    avatar_icon = forms.ChoiceField(
        label="Standard-Icon",
        required=False,
        choices=[("", "Eigenes Foto / Initialen"), *Profile.AvatarIcon.choices],
        widget=forms.RadioSelect,
    )

    class Meta:
        model = Profile
        fields = (
            "photo",
            "avatar_icon",
            "first_name",
            "last_name",
            "vulgo",
            "email",
            "academic_title",
            "degree_program",
            "birth_date",
        )
        labels = {
            "vulgo": "v/o",
            "academic_title": "Abschluss / Titel",
            "degree_program": "Studiengang",
        }
        help_texts = {
            "academic_title": "Beispielsweise Dr. med., MSc, BSc oder Prof. Dr.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.user_id:
            self.initial.setdefault("email", self.instance.user.email)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        user = self.cleaned_data.get("user")
        user_id = user.pk if user else self.instance.user_id
        if User.objects.filter(email__iexact=email).exclude(pk=user_id).exists():
            raise forms.ValidationError("Für diese E-Mail-Adresse besteht bereits ein Konto.")
        return email

    @transaction.atomic
    def save(self, commit=True):
        return super().save(commit=commit)

    def _save_m2m(self):
        super()._save_m2m()
        # Also runs after save(commit=False) in the Django admin. Update only
        # email to avoid triggering the User signal that saves the profile again.
        email = self.cleaned_data["email"]
        User.objects.filter(pk=self.instance.user_id).update(email=email)
        self.instance.user.email = email

    def clean_photo(self):
        return validate_profile_photo(self.cleaned_data.get("photo"))


class UserWithProfileCreationForm(forms.ModelForm):
    """Provision a member account without a password.

    The member sets their own first password through the account-activation
    email link (see AccountActivationForm) rather than an admin choosing one
    on their behalf.
    """

    email = forms.EmailField(required=True)
    first_name = forms.CharField(label="Vorname", max_length=150)
    last_name = forms.CharField(label="Name", max_length=150)
    vulgo = forms.CharField(label="v/o", max_length=150, required=False)
    photo = forms.ImageField(label="Profilfoto", required=False)
    avatar_icon = forms.ChoiceField(
        label="Standard-Icon",
        required=False,
        choices=[("", "Eigenes Foto / Initialen"), *Profile.AvatarIcon.choices],
        widget=forms.RadioSelect,
    )
    academic_title = forms.CharField(
        label="Abschluss / Titel",
        max_length=150,
        required=False,
        help_text="Beispielsweise Dr. med., MSc, BSc oder Prof. Dr.",
    )
    degree_program = forms.CharField(label="Studiengang", max_length=255, required=False)
    birth_date = forms.DateField(
        label="Geburtsdatum",
        required=False,
        input_formats=[ISO_DATE_INPUT_FORMAT],
        widget=html5_date_input(),
    )
    entry_year = forms.IntegerField(label="Eintrittsjahr", required=False, min_value=1)
    entry_semester = forms.ChoiceField(
        label="Eintrittssemester",
        required=False,
        choices=[("", "---------"), *Profile.Semester.choices],
    )
    exit_year = forms.IntegerField(label="Austrittsjahr", required=False, min_value=1)
    exit_semester = forms.ChoiceField(
        label="Austrittssemester",
        required=False,
        choices=[("", "---------"), *Profile.Semester.choices],
    )
    death_date = forms.DateField(
        label="Todesdatum",
        required=False,
        input_formats=[ISO_DATE_INPUT_FORMAT],
        widget=html5_date_input(),
    )
    roles = RoleMultipleChoiceField(
        queryset=Role.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = User
        fields = ("email",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop("username", None)
        self.fields["roles"].queryset = Role.objects.order_by("code")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Für diese E-Mail-Adresse besteht bereits ein Konto.")
        return email

    def clean_photo(self):
        return validate_profile_photo(self.cleaned_data.get("photo"))

    def save(self, commit=True):
        user = super().save(commit=False)
        while True:
            username = f"mitglied-{get_random_string(32).lower()}"
            if not User.objects.filter(username=username).exists():
                user.username = username
                break
        user.email = self.cleaned_data["email"]
        user.set_unusable_password()
        if commit:
            user.save()
            profile = user.profile
            profile.first_name = self.cleaned_data["first_name"]
            profile.last_name = self.cleaned_data["last_name"]
            profile.vulgo = self.cleaned_data["vulgo"]
            profile.academic_title = self.cleaned_data["academic_title"]
            profile.degree_program = self.cleaned_data["degree_program"]
            profile.birth_date = self.cleaned_data["birth_date"]
            profile.entry_year = self.cleaned_data["entry_year"]
            profile.entry_semester = self.cleaned_data["entry_semester"]
            profile.exit_year = self.cleaned_data["exit_year"]
            profile.exit_semester = self.cleaned_data["exit_semester"]
            profile.death_date = self.cleaned_data["death_date"]
            if self.cleaned_data.get("photo"):
                profile.photo = self.cleaned_data["photo"]
            profile.avatar_icon = self.cleaned_data["avatar_icon"]
            profile.full_clean()
            profile.save()
            profile.roles.set(self.cleaned_data["roles"])
        return user


class AdminUserPasswordResetForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label="Neues Passwort",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=SetPasswordForm.base_fields["new_password1"].help_text,
    )
    new_password2 = forms.CharField(
        label="Neues Passwort bestätigen",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Zur Bestätigung das neue Passwort erneut eingeben.",
    )


class PortalPasswordResetForm(PasswordResetForm):
    """Project-specific subclass only for neutral reset-mail throttling."""

    def save(self, *args, **kwargs):
        request = kwargs.get("request")
        email = self.cleaned_data.get("email", "")
        if throttling.is_password_reset_throttled(request, email):
            return
        throttling.register_password_reset_attempt(request, email)
        return super().save(*args, **kwargs)


class AccountActivationForm(PortalPasswordResetForm):
    """Send an activation link only for one unambiguous, provisioned account."""

    def get_users(self, email):
        user_model = get_user_model()
        users = list(
            user_model._default_manager.filter(
                email__iexact=email,
                is_active=True,
            ).order_by("pk")[:2]
        )
        if len(users) != 1:
            return ()
        return users


class AccountActivationSetPasswordForm(AdminUserPasswordResetForm):
    pass


class ProfileForm(ProfileBaseForm):
    pass


class AdminProfileForm(ProfileBaseForm):
    entry_year = forms.IntegerField(label="Eintrittsjahr", required=False, min_value=1)
    entry_semester = forms.ChoiceField(
        label="Eintrittssemester",
        required=False,
        choices=[("", "---------"), *Profile.Semester.choices],
    )
    exit_year = forms.IntegerField(label="Austrittsjahr", required=False, min_value=1)
    exit_semester = forms.ChoiceField(
        label="Austrittssemester",
        required=False,
        choices=[("", "---------"), *Profile.Semester.choices],
    )
    death_date = forms.DateField(
        label="Todesdatum",
        required=False,
        input_formats=[ISO_DATE_INPUT_FORMAT],
        widget=html5_date_input(),
    )
    confirm_death_date_effects = forms.BooleanField(
        label="Ich bestätige die Folgen des Todesdatums.",
        required=False,
        help_text="Das Setzen eines Todesdatums deaktiviert den Benutzerzugang und nimmt das Mitglied in die Totentafel auf.",
    )
    roles = RoleMultipleChoiceField(
        queryset=Role.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta(ProfileBaseForm.Meta):
        fields = ProfileBaseForm.Meta.fields + (
            "entry_year",
            "entry_semester",
            "exit_year",
            "exit_semester",
            "death_date",
            "roles",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["roles"].queryset = Role.objects.order_by("code")

    def clean(self):
        cleaned_data = super().clean()
        death_date = cleaned_data.get("death_date")
        previous_death_date = self.instance.death_date if self.instance.pk else None
        if death_date and not previous_death_date and not cleaned_data.get("confirm_death_date_effects"):
            self.add_error(
                "confirm_death_date_effects",
                "Bitte bestätige die Folgen, bevor du erstmals ein Todesdatum setzt.",
            )
        return cleaned_data

    def save(self, commit=True):
        profile = super().save(commit=commit)
        if commit:
            profile.roles.set(self.cleaned_data["roles"])
        return profile


class MemorialEntryForm(forms.ModelForm):
    birth_date = forms.DateField(
        label="Geburtsdatum",
        required=False,
        input_formats=[ISO_DATE_INPUT_FORMAT],
        widget=html5_date_input(),
    )
    death_date = forms.DateField(
        label="Todesdatum",
        required=False,
        input_formats=[ISO_DATE_INPUT_FORMAT],
        widget=html5_date_input(),
    )

    class Meta:
        model = MemorialEntry
        fields = (
            "member_profile",
            "display_name",
            "import_key",
            "birth_date",
            "birth_date_display",
            "death_date",
            "death_date_display",
            "sort_date",
            "sort_order",
            "is_published",
            "is_honorary_member",
            "legacy_marker",
        )
        widgets = {
            "sort_date": html5_date_input(),
        }


class PortalMemorialEntryForm(forms.ModelForm):
    birth_date = forms.DateField(
        label="Geburtsdatum",
        required=False,
        input_formats=[ISO_DATE_INPUT_FORMAT],
        widget=html5_date_input(),
    )
    death_date = forms.DateField(
        label="Todesdatum",
        required=False,
        input_formats=[ISO_DATE_INPUT_FORMAT],
        widget=html5_date_input(),
    )
    obituary_upload = forms.FileField(
        label="Nachruf als PDF",
        required=False,
        help_text="Optional. Erlaubt sind nur PDF-Dateien bis maximal 20 MB.",
    )
    obituary_remove = forms.BooleanField(
        label="Nachruf entfernen",
        required=False,
    )

    class Meta:
        model = MemorialEntry
        fields = (
            "member_profile",
            "display_name",
            "birth_date",
            "death_date",
            "is_honorary_member",
        )
        labels = {
            "member_profile": "Mitgliederprofil",
            "display_name": "Anzeigename",
            "is_honorary_member": "Als Ehrenphilister markieren",
        }
        help_texts = {
            "member_profile": "Optional. Verknüpft den Eintrag mit einem internen Profil.",
            "display_name": "Name, wie er auf der Totentafel erscheinen soll.",
            "is_honorary_member": "Setzt automatisch ein * hinter den Namen.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk or not self.instance.obituary_document_id:
            self.fields["obituary_remove"].widget = forms.HiddenInput()

    def clean_obituary_upload(self):
        upload = self.cleaned_data.get("obituary_upload")
        if not upload:
            return upload

        if upload.size > MAX_OBITUARY_FILE_SIZE:
            raise forms.ValidationError("Die PDF-Datei darf höchstens 20 MB gross sein.")
        if getattr(upload, "content_type", "") != "application/pdf":
            raise forms.ValidationError("Es sind nur PDF-Dateien mit dem MIME-Type application/pdf erlaubt.")
        if not upload.name.lower().endswith(".pdf"):
            raise forms.ValidationError("Bitte lade eine Datei mit der Endung .pdf hoch.")

        header = upload.read(5)
        upload.seek(0)
        if header != b"%PDF-":
            raise forms.ValidationError("Die hochgeladene Datei ist kein gültiges PDF.")
        return upload

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("obituary_upload") and cleaned_data.get("obituary_remove"):
            self.add_error("obituary_remove", "Beim Ersetzen muss der Nachruf nicht zusätzlich entfernt werden.")
        return cleaned_data

    def save(self, commit=True):
        entry = super().save(commit=False)
        entry.birth_date_display = ""
        entry.death_date_display = ""
        entry.sort_date = entry.death_date
        entry.sort_order = 0
        entry.is_published = True
        if commit:
            entry.save()
        return entry
