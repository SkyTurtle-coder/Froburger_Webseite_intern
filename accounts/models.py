import hashlib
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from documents.models import Document

from .roles import ROLE_CHOICES, ROLE_LABELS


class Role(models.Model):
    code = models.CharField(max_length=32, choices=ROLE_CHOICES, unique=True)

    class Meta:
        ordering = ["code"]

    @property
    def display_label(self):
        return ROLE_LABELS.get(self.code, self.code)

    def __str__(self):
        return self.display_label


class Profile(models.Model):
    class Semester(models.TextChoices):
        FRUEHLINGSSEMESTER = "FS", "FS"
        HERBSTSEMESTER = "HS", "HS"

    class MembershipStatus(models.TextChoices):
        AKTIV = "active", "Aktiv"
        INAKTIV = "inactive", "Inaktiv"
        VERSTORBEN = "deceased", "Verstorben"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    photo = models.ImageField(upload_to="avatars/", blank=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    vulgo = models.CharField(max_length=150, blank=True)
    academic_title = models.CharField("Abschluss / Titel", max_length=150, blank=True)
    degree_program = models.CharField("Studiengang", max_length=255, blank=True)
    entry_year = models.PositiveSmallIntegerField("Eintrittsjahr", null=True, blank=True)
    entry_semester = models.CharField("Eintrittssemester", max_length=2, choices=Semester.choices, blank=True)
    exit_year = models.PositiveSmallIntegerField("Austrittsjahr", null=True, blank=True)
    exit_semester = models.CharField("Austrittssemester", max_length=2, choices=Semester.choices, blank=True)
    birth_date = models.DateField("Geburtsdatum", null=True, blank=True)
    death_date = models.DateField("Todesdatum", null=True, blank=True)
    roles = models.ManyToManyField(Role, blank=True, related_name="profiles")

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        if self.vulgo:
            return f"{self.first_name} {self.last_name} v/o {self.vulgo}"
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def full_name_with_title(self):
        if self.academic_title:
            return f"{self.academic_title} {self.full_name}".strip()
        return self.full_name

    @property
    def memorial_display_name(self):
        parts = [self.academic_title.strip(), self.first_name.strip(), self.last_name.strip()]
        name = " ".join(part for part in parts if part)
        if self.vulgo.strip():
            return f"{name} v/o {self.vulgo.strip()}".strip()
        return name

    def role_codes(self):
        return list(self.roles.values_list("code", flat=True))

    def has_role(self, role_code):
        return self.roles.filter(code=role_code).exists()

    def has_any_role(self, *role_codes):
        return self.roles.filter(code__in=role_codes).exists()

    def can_manage_roles(self):
        return self.has_role("ADMIN")

    def can_manage_events(self):
        return self.has_any_role("ADMIN", "WEB_X")

    def can_access_sensitive_documents(self):
        return self.has_any_role("ADMIN", "BURSCH", "ALTFROBURGER")

    def can_upload_sensitive_documents(self):
        return self.can_access_sensitive_documents()

    @property
    def is_deceased(self):
        return bool(self.death_date)

    @property
    def is_inactive_member(self):
        return bool(self.exit_year and self.exit_semester and not self.death_date)

    @property
    def is_active_member(self):
        return not self.is_inactive_member and not self.is_deceased

    @property
    def membership_status(self):
        if self.death_date:
            return self.MembershipStatus.VERSTORBEN
        if self.exit_year and self.exit_semester:
            return self.MembershipStatus.INAKTIV
        return self.MembershipStatus.AKTIV

    @property
    def membership_status_label(self):
        return self.MembershipStatus(self.membership_status).label

    @property
    def entry_term_display(self):
        return self._term_display(self.entry_year, self.entry_semester)

    @property
    def exit_term_display(self):
        return self._term_display(self.exit_year, self.exit_semester)

    @property
    def membership_period_display(self):
        if not self.entry_term_display:
            return ""
        if self.exit_term_display:
            return f"{self.entry_term_display} â€“ {self.exit_term_display}"
        return f"seit {self.entry_term_display}"

    @property
    def editable_profile_completion(self):
        fields = (
            bool(self.academic_title.strip()),
            bool(self.degree_program.strip()),
            bool(self.birth_date),
        )
        completed = sum(1 for is_set in fields if is_set)
        total = len(fields)
        return {
            "completed": completed,
            "total": total,
            "percent": int((completed / total) * 100) if total else 100,
        }

    def clean(self):
        super().clean()
        errors = {}
        self._validate_term_pair("entry_year", "entry_semester", "Eintritt", errors)
        self._validate_term_pair("exit_year", "exit_semester", "Austritt", errors)

        entry_value = self._term_sort_value(self.entry_year, self.entry_semester)
        exit_value = self._term_sort_value(self.exit_year, self.exit_semester)
        if entry_value is not None and exit_value is not None and exit_value < entry_value:
            errors["exit_year"] = "Der Austritt darf nicht vor dem Eintritt liegen."
            errors["exit_semester"] = "Der Austritt darf nicht vor dem Eintritt liegen."

        today = timezone.localdate()
        if self.birth_date and self.birth_date > today:
            errors["birth_date"] = "Das Geburtsdatum darf nicht in der Zukunft liegen."
        if self.death_date and self.death_date > today:
            errors["death_date"] = "Das Todesdatum darf nicht in der Zukunft liegen."
        if self.birth_date and self.death_date and self.death_date < self.birth_date:
            errors["death_date"] = "Das Todesdatum darf nicht vor dem Geburtsdatum liegen."

        if errors:
            raise ValidationError(errors)

    @classmethod
    def _term_display(cls, year, semester):
        if not year or not semester:
            return ""
        return f"{year} {semester}"

    @classmethod
    def _term_sort_value(cls, year, semester):
        if not year or not semester:
            return None
        semester_order = {
            cls.Semester.FRUEHLINGSSEMESTER: 0,
            cls.Semester.HERBSTSEMESTER: 1,
        }
        return (int(year), semester_order.get(semester, 99))

    def _validate_term_pair(self, year_field, semester_field, label, errors):
        year_value = getattr(self, year_field)
        semester_value = getattr(self, semester_field)
        if bool(year_value) != bool(semester_value):
            message = f"{label}sjahr und {label.lower()}ssemester mÃ¼ssen gemeinsam gesetzt oder gemeinsam leer sein."
            errors[year_field] = message
            errors[semester_field] = message


class MemorialEntry(models.Model):
    member_profile = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memorial_entries",
        verbose_name="Mitgliederprofil",
    )
    obituary_document = models.ForeignKey(
        Document,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memorial_entries",
        verbose_name="Nachruf",
    )
    display_name = models.CharField("Anzeigename", max_length=255)
    import_key = models.CharField("Import-Schlüssel", max_length=64, blank=True, null=True, unique=True)
    birth_date = models.DateField("Geburtsdatum", null=True, blank=True)
    birth_date_display = models.CharField("Geburtsdatum Anzeige", max_length=80, blank=True)
    death_date = models.DateField("Todesdatum", null=True, blank=True)
    death_date_display = models.CharField("Todesdatum Anzeige", max_length=80, blank=True)
    sort_date = models.DateField("Sortierdatum", null=True, blank=True)
    sort_order = models.PositiveIntegerField("Manuelle Sortierung", default=0)
    is_published = models.BooleanField("Veröffentlicht", default=False)
    is_honorary_member = models.BooleanField("Ehrenphilister", default=False)
    legacy_marker = models.CharField("Legacy-Markierung", max_length=16, blank=True)
    is_profile_generated = models.BooleanField("Automatisch aus Profil erzeugt", default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["member_profile"],
                condition=Q(is_profile_generated=True),
                name="accounts_memorialentry_unique_generated_profile",
            )
        ]

    def __str__(self):
        return self.display_name

    def clean(self):
        super().clean()
        errors = {}
        today = timezone.localdate()
        if self.birth_date and self.birth_date > today:
            errors["birth_date"] = "Das Geburtsdatum darf nicht in der Zukunft liegen."
        if self.death_date and self.death_date > today:
            errors["death_date"] = "Das Todesdatum darf nicht in der Zukunft liegen."
        if self.birth_date and self.death_date and self.death_date < self.birth_date:
            errors["death_date"] = "Das Todesdatum darf nicht vor dem Geburtsdatum liegen."
        if self.birth_date and self.birth_date_display.strip():
            self.birth_date_display = ""
        if self.death_date and self.death_date_display.strip():
            self.death_date_display = ""
        if not self.sort_date and self.death_date:
            self.sort_date = self.death_date
        if errors:
            raise ValidationError(errors)

    @property
    def birth_display(self):
        if self.birth_date:
            return self.birth_date.strftime("%d.%m.%Y")
        return self.birth_date_display.strip()

    @property
    def death_display(self):
        if self.death_date:
            return self.death_date.strftime("%d.%m.%Y")
        return self.death_date_display.strip()

    @property
    def display_name_with_markers(self):
        suffix = "*" if self.is_honorary_member else ""
        return f"{self.display_name}{suffix}".strip()


class CalendarSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="calendar_subscriptions")
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    token_hint = models.CharField(max_length=16, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"Calendar subscription #{self.pk} for {self.user.username}"

    @property
    def is_active(self):
        return self.revoked_at is None and self.user.is_active

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])

    @classmethod
    def issue_for_user(cls, user):
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        subscription = cls.objects.create(
            user=user,
            token_hash=token_hash,
            token_hint=raw_token[-8:],
        )
        return subscription, raw_token

