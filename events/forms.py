from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import Event, EventSignup, EventSignupColumn


class EventForm(forms.ModelForm):
    start = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )
    end = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )

    class Meta:
        model = Event
        fields = (
            "title",
            "slug",
            "short_description",
            "description",
            "start",
            "end",
            "location",
            "status",
            "is_public",
            "is_cancelled",
            "show_on_homepage",
        )
        labels = {
            "title": "Titel",
            "slug": "URL-Kürzel",
            "short_description": "Kurzbeschreibung",
            "description": "Beschreibung",
            "start": "Beginn",
            "end": "Ende",
            "location": "Ort",
            "status": "Status",
            "is_public": "Öffentlich sichtbar",
            "is_cancelled": "Abgesagt",
            "show_on_homepage": "Auf Startseite zeigen",
        }
        help_texts = {
            "slug": "Leer lassen für automatische Generierung.",
            "short_description": "Pflicht für öffentliche Anlässe.",
            "location": "Pflicht für öffentliche Anlässe.",
            "is_cancelled": "Abgesagte Anlässe bleiben im Kalender als Absage sichtbar.",
        }


class EventSignupColumnForm(forms.ModelForm):
    class Meta:
        model = EventSignupColumn
        fields = (
            "label",
            "field_type",
            "sort_order",
            "is_active",
            "is_required",
            "is_public",
            "field_options",
            "placeholder",
        )
        labels = {
            "label": "Spaltentitel",
            "field_type": "Feldtyp",
            "sort_order": "Reihenfolge",
            "is_active": "Aktiv",
            "is_required": "Pflichtfeld",
            "is_public": "Öffentlich sichtbar",
            "field_options": "Auswahloptionen",
            "placeholder": "Platzhalter",
        }
        help_texts = {
            "label": "Spaltenname.",
            "field_type": "Feldtyp.",
            "sort_order": "Kleinere Werte stehen weiter links.",
            "is_active": "Nur aktive Spalten werden verwendet.",
            "is_required": "Pflichtfeld.",
            "is_public": "In der öffentlichen Liste sichtbar.",
            "field_options": "Eine Option pro Zeile.",
            "placeholder": "Optional.",
        }


class BaseEventSignupColumnFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        labels = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            label = (form.cleaned_data.get("label") or "").strip()
            if not label:
                continue
            key = label.casefold()
            if key in labels:
                raise forms.ValidationError("Zusatzspalten müssen pro Anlass unterschiedliche Titel haben.")
            labels.add(key)


EventSignupColumnFormSet = inlineformset_factory(
    Event,
    EventSignupColumn,
    form=EventSignupColumnForm,
    formset=BaseEventSignupColumnFormSet,
    extra=0,
    can_delete=True,
)


class EventSignupPublicForm(forms.Form):
    vulgo = forms.CharField(label="Vulgo", max_length=80)
    attending = forms.TypedChoiceField(
        label="Anwesend",
        choices=((True, "Ja"), (False, "Nein")),
        coerce=lambda value: value in (True, "True", "true", "1", 1, "yes", "on"),
        empty_value=None,
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, event, **kwargs):
        self.event = event
        self.columns = list(event.active_signup_columns())
        super().__init__(*args, **kwargs)
        for column in self.columns:
            field_name = f"col_{column.key}"
            if column.field_type == EventSignupColumn.FIELD_TYPE_TEXTAREA:
                field = forms.CharField(
                    label=column.label,
                    max_length=2000,
                    required=column.is_required,
                    widget=forms.Textarea(attrs={"rows": 4, "placeholder": column.placeholder}),
                )
            elif column.field_type == EventSignupColumn.FIELD_TYPE_SELECT:
                field = forms.ChoiceField(
                    label=column.label,
                    required=column.is_required,
                    choices=[("", "Bitte wählen")] + [(option, option) for option in column.options],
                )
            elif column.field_type == EventSignupColumn.FIELD_TYPE_CHECKBOX:
                field = forms.BooleanField(
                    label=column.label,
                    required=False,
                    help_text="Nur intern sichtbar." if not column.is_public else "",
                )
            else:
                field = forms.CharField(
                    label=column.label,
                    max_length=200,
                    required=column.is_required,
                    widget=forms.TextInput(attrs={"placeholder": column.placeholder}),
                )

            if not column.is_public and column.field_type != EventSignupColumn.FIELD_TYPE_CHECKBOX:
                field.help_text = "Nur intern sichtbar."

            self.fields[field_name] = field

    def clean_website(self):
        value = (self.cleaned_data.get("website") or "").strip()
        if value:
            raise forms.ValidationError("Ungültige Anfrage.")
        return ""

    def clean_vulgo(self):
        value = (self.cleaned_data.get("vulgo") or "").strip()
        value = " ".join(value.split())
        if not value:
            raise forms.ValidationError("Bitte ein Vulgo angeben.")
        return value

    def clean(self):
        cleaned_data = super().clean()
        if self.event.is_signup_closed:
            raise forms.ValidationError("Die Anmeldung für diesen Anlass ist geschlossen.")
        return cleaned_data

    def build_values(self):
        values = {}
        for column in self.columns:
            field_name = f"col_{column.key}"
            value = self.cleaned_data.get(field_name)
            if column.field_type == EventSignupColumn.FIELD_TYPE_CHECKBOX:
                values[column.key] = bool(value)
            else:
                values[column.key] = (value or "").strip()
        return values


class EventSignupManageForm(forms.Form):
    signup_id = forms.IntegerField(widget=forms.HiddenInput)
    vulgo = forms.CharField(label="Vulgo", max_length=80)
    attending = forms.TypedChoiceField(
        label="Anwesend",
        choices=((True, "Ja"), (False, "Nein")),
        coerce=lambda value: value in (True, "True", "true", "1", 1, "yes", "on"),
        empty_value=None,
    )
    delete = forms.BooleanField(label="Löschen", required=False, widget=forms.HiddenInput())

    def __init__(self, *args, event, signup=None, **kwargs):
        self.event = event
        self.signup = signup
        self.columns = list(event.active_signup_columns())
        super().__init__(*args, **kwargs)
        self.fields["signup_id"].initial = signup.pk if signup else None
        self.fields["vulgo"].initial = signup.vulgo if signup else ""
        self.fields["attending"].initial = signup.attending if signup else None
        for column in self.columns:
            field_name = f"col_{column.key}"
            if column.field_type == EventSignupColumn.FIELD_TYPE_TEXTAREA:
                field = forms.CharField(
                    label=column.label,
                    max_length=2000,
                    required=False,
                    widget=forms.Textarea(attrs={"rows": 3}),
                )
            elif column.field_type == EventSignupColumn.FIELD_TYPE_SELECT:
                field = forms.ChoiceField(
                    label=column.label,
                    required=False,
                    choices=[("", "Bitte wählen")] + [(option, option) for option in column.options],
                )
            elif column.field_type == EventSignupColumn.FIELD_TYPE_CHECKBOX:
                field = forms.BooleanField(label=column.label, required=False)
            else:
                field = forms.CharField(label=column.label, max_length=200, required=False)
            self.fields[field_name] = field
            if signup:
                self.fields[field_name].initial = signup.values.get(
                    column.key,
                    False if column.field_type == EventSignupColumn.FIELD_TYPE_CHECKBOX else "",
                )

    def clean_vulgo(self):
        value = (self.cleaned_data.get("vulgo") or "").strip()
        value = " ".join(value.split())
        if not value:
            raise forms.ValidationError("Bitte ein Vulgo angeben.")
        return value

    def build_values(self):
        values = {}
        for column in self.columns:
            value = self.cleaned_data.get(f"col_{column.key}")
            if column.field_type == EventSignupColumn.FIELD_TYPE_CHECKBOX:
                values[column.key] = bool(value)
            else:
                values[column.key] = (value or "").strip()
        return values
