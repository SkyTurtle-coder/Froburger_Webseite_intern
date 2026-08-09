from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import MemorialEntry, Profile, Role


MAX_OBITUARY_FILE_SIZE = 20 * 1024 * 1024
ISO_DATE_INPUT_FORMAT = "%Y-%m-%d"


def html5_date_input():
    return forms.DateInput(format=ISO_DATE_INPUT_FORMAT, attrs={"type": "date"})


class RoleMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return obj.display_label


class ProfileBaseForm(forms.ModelForm):
    birth_date = forms.DateField(
        label="Geburtsdatum",
        required=False,
        input_formats=[ISO_DATE_INPUT_FORMAT],
        widget=html5_date_input(),
    )

    class Meta:
        model = Profile
        fields = (
            "photo",
            "first_name",
            "last_name",
            "vulgo",
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


class UserWithProfileCreationForm(UserCreationForm):
    email = forms.EmailField(required=False)
    first_name = forms.CharField(label="Vorname", max_length=150)
    last_name = forms.CharField(label="Name", max_length=150)
    vulgo = forms.CharField(label="v/o", max_length=150, required=False)
    photo = forms.ImageField(label="Profilfoto", required=False)
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

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["roles"].queryset = Role.objects.order_by("code")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
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
            profile.full_clean()
            profile.save()
            profile.roles.set(self.cleaned_data["roles"])
        return user


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
