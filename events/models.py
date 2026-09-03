import re
import uuid
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.template.defaultfilters import slugify
from django.urls import reverse
from django.utils import timezone


class Event(models.Model):
    STATUS_CHOICES = [
        ("INTERN", "Intern"),
        ("OFF", "Off"),
        ("INOFF", "Inoff"),
        ("IAOFF", "Iaoff"),
        ("HOCHOFF", "Hochoff"),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    short_description = models.CharField(max_length=280, blank=True)
    description = models.TextField(blank=True)
    start = models.DateTimeField()
    end = models.DateTimeField()
    location = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    is_public = models.BooleanField(default=False)
    is_cancelled = models.BooleanField(default=False)
    show_on_homepage = models.BooleanField(default=False)
    signup_enabled = models.BooleanField(default=True)
    signup_deadline_at = models.DateTimeField(null=True, blank=True)
    calendar_uid = models.CharField(max_length=255, unique=True, blank=True, editable=False)
    calendar_sequence = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start", "title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("event-list")

    def clean(self):
        if self.end and self.start and self.end < self.start:
            raise ValidationError({"end": "Das Ende muss nach dem Start liegen."})

        if self.is_public:
            errors = {}
            if not self.short_description.strip():
                errors["short_description"] = "Öffentliche Anlässe benötigen eine Kurzbeschreibung."
            if not self.location.strip():
                errors["location"] = "Öffentliche Anlässe benötigen einen Ort."
            if self.status == "INTERN" and self.show_on_homepage:
                errors["show_on_homepage"] = "Interne Anlässe dürfen nicht auf der Startseite erscheinen."
            if errors:
                raise ValidationError(errors)
        elif self.show_on_homepage:
            raise ValidationError({"show_on_homepage": "Startseitenanzeige ist nur für WordPress-sichtbare Anlässe möglich."})

    def save(self, *args, **kwargs):
        if not self.calendar_uid:
            self.calendar_uid = f"event-{uuid.uuid4()}@avfroburger.ch"

        if not self.slug:
            base_slug = slugify(self.title)[:210] or "anlass"
            slug = base_slug
            counter = 2
            while Event.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f"{base_slug[:210]}-{counter}"
                counter += 1
            self.slug = slug

        if self.pk:
            previous = Event.objects.filter(pk=self.pk).values(
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
            ).first()
            if previous is not None:
                current = {
                    "title": self.title,
                    "slug": self.slug,
                    "short_description": self.short_description,
                    "description": self.description,
                    "start": self.start,
                    "end": self.end,
                    "location": self.location,
                    "status": self.status,
                    "is_public": self.is_public,
                    "is_cancelled": self.is_cancelled,
                }
                if previous != current:
                    self.calendar_sequence += 1

        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        retention_days = max(1, int(getattr(settings, "CALENDAR_PAST_RETENTION_DAYS", 90)))
        EventCalendarTombstone.objects.update_or_create(
            calendar_uid=self.calendar_uid,
            defaults={
                "title": self.title,
                "start": self.start,
                "end": self.end,
                "location": self.location,
                "description": self.short_description or self.description,
                "was_public": self.is_public,
                "calendar_sequence": self.calendar_sequence + 1,
                "cancelled_at": timezone.now(),
                "expires_at": timezone.now() + timedelta(days=retention_days),
            },
        )
        return super().delete(*args, **kwargs)

    @property
    def timezone_name(self):
        return timezone.get_current_timezone_name()

    @property
    def public_detail_path(self):
        prefix = settings.PUBLIC_EVENT_DETAIL_PATH_PREFIX.strip("/")
        return f"/{prefix}/{self.slug}/"

    @property
    def public_source_url(self):
        if not settings.PUBLIC_EVENT_SOURCE_BASE_URL:
            return ""
        return f"{settings.PUBLIC_EVENT_SOURCE_BASE_URL}{self.public_detail_path}"

    @property
    def wordpress_fallback_url(self):
        if not settings.PUBLIC_WORDPRESS_SITE_URL:
            return ""
        return f"{settings.PUBLIC_WORDPRESS_SITE_URL}/anlaesse/#event-{self.slug}"

    @property
    def signup_deadline(self):
        if self.signup_deadline_at:
            return self.signup_deadline_at

        local_start = timezone.localtime(self.start)
        deadline_local = datetime.combine(local_start.date(), time(hour=0, minute=1))
        return timezone.make_aware(deadline_local, timezone.get_current_timezone())

    @property
    def is_signup_closed(self):
        return timezone.now() >= self.signup_deadline

    def active_signup_columns(self):
        return self.signup_columns.filter(is_active=True).order_by("sort_order", "created_at", "pk")


class EventSignupColumn(models.Model):
    FIELD_TYPE_TEXT = "text"
    FIELD_TYPE_TEXTAREA = "textarea"
    FIELD_TYPE_SELECT = "select"
    FIELD_TYPE_CHECKBOX = "checkbox"
    FIELD_TYPE_CHOICES = [
        (FIELD_TYPE_TEXT, "Text"),
        (FIELD_TYPE_TEXTAREA, "Textarea"),
        (FIELD_TYPE_SELECT, "Select"),
        (FIELD_TYPE_CHECKBOX, "Checkbox"),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="signup_columns")
    label = models.CharField(max_length=80)
    key = models.SlugField(max_length=48, editable=False)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPE_CHOICES, default=FIELD_TYPE_TEXT)
    sort_order = models.PositiveIntegerField(default=10)
    is_active = models.BooleanField(default=True)
    is_required = models.BooleanField(default=False)
    is_public = models.BooleanField(default=False)
    field_options = models.TextField(blank=True)
    placeholder = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "created_at", "pk"]

    def __str__(self):
        return f"{self.event.title}: {self.label}"

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = f"col-{uuid.uuid4().hex[:12]}"
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.field_type == self.FIELD_TYPE_SELECT and not self.options:
            raise ValidationError({"field_options": "Select-Felder brauchen mindestens eine Option."})

    @property
    def options(self):
        return [line.strip() for line in self.field_options.splitlines() if line.strip()]


class EventSignupQuerySet(models.QuerySet):
    def active(self):
        return self.filter(deleted_at__isnull=True)

    def public_visible(self):
        return self.active().filter(is_public=True)

    def deleted(self):
        return self.filter(deleted_at__isnull=False)


class EventSignupManager(models.Manager):
    def get_queryset(self):
        return EventSignupQuerySet(self.model, using=self._db).active()

    def public_visible(self):
        return self.get_queryset().public_visible()


class EventSignupAllObjectsManager(models.Manager):
    def get_queryset(self):
        return EventSignupQuerySet(self.model, using=self._db)

    def active(self):
        return self.get_queryset().active()

    def public_visible(self):
        return self.get_queryset().public_visible()

    def deleted(self):
        return self.get_queryset().deleted()


class EventSignup(models.Model):
    SOURCE_PUBLIC_FORM = "public_form"
    SOURCE_INTERNAL = "internal"
    SOURCE_API = "api"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="signups")
    vulgo = models.CharField(max_length=80)
    normalized_vulgo = models.CharField(max_length=80, editable=False)
    attending = models.BooleanField()
    is_public = models.BooleanField(
        default=True,
        verbose_name="Öffentlich sichtbar",
        help_text="Steuert, ob dieser Eintrag auf der öffentlichen Anlassseite erscheint.",
    )
    values = models.JSONField(default=dict, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    delete_reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EventSignupManager()
    all_objects = EventSignupAllObjectsManager()

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "normalized_vulgo"],
                condition=Q(deleted_at__isnull=True),
                name="unique_event_signup_vulgo",
            )
        ]

    def __str__(self):
        return f"{self.event.title}: {self.vulgo}"

    @staticmethod
    def normalize_vulgo(value):
        compact = re.sub(r"\s+", " ", (value or "").strip())
        return compact.casefold()

    def clean(self):
        errors = {}
        clean_vulgo = re.sub(r"\s+", " ", (self.vulgo or "").strip())
        if not clean_vulgo:
            errors["vulgo"] = "Bitte ein Vulgo angeben."
        else:
            self.vulgo = clean_vulgo
            self.normalized_vulgo = self.normalize_vulgo(clean_vulgo)

        if self.attending not in (True, False):
            errors["attending"] = "Bitte angeben, ob du anwesend bist."

        if not isinstance(self.values, dict):
            errors["values"] = "Ungültige Zusatzwerte."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, actor=None, source=None, **kwargs):
        is_create = self._state.adding
        previous = None
        if not is_create and self.pk:
            previous = EventSignup.all_objects.filter(pk=self.pk).values(
                "vulgo",
                "normalized_vulgo",
                "attending",
                "is_public",
                "values",
                "deleted_at",
                "delete_reason",
            ).first()

        self.full_clean()
        result = super().save(*args, **kwargs)

        if is_create:
            SignupAuditLog.record(
                signup=self,
                event=self.event,
                action=SignupAuditLog.ACTION_CREATED,
                actor=actor,
                source=source or self.SOURCE_API,
                changes={},
            )
            return result

        if previous is None:
            return result

        changes = self._build_changes(previous)
        if not changes:
            return result

        action = SignupAuditLog.ACTION_UPDATED
        if previous["deleted_at"] is None and self.deleted_at is not None:
            action = SignupAuditLog.ACTION_DELETED
        elif previous["deleted_at"] is not None and self.deleted_at is None:
            action = SignupAuditLog.ACTION_RESTORED
        elif previous["is_public"] != self.is_public:
            action = SignupAuditLog.ACTION_SHOWN if self.is_public else SignupAuditLog.ACTION_HIDDEN

        SignupAuditLog.record(
            signup=self,
            event=self.event,
            action=action,
            actor=actor,
            source=source or self.SOURCE_INTERNAL,
            changes=changes,
        )
        return result

    def delete(self, *args, hard=False, actor=None, reason="", source=None, **kwargs):
        if hard:
            SignupAuditLog.record(
                signup=self,
                event=self.event,
                action=SignupAuditLog.ACTION_PURGED,
                actor=actor,
                source=source or self.SOURCE_INTERNAL,
                changes={},
            )
            return super().delete(*args, **kwargs)

        return self.soft_delete(actor=actor, reason=reason, source=source)

    def soft_delete(self, *, actor=None, reason="", source=None):
        if self.deleted_at is not None:
            return

        self.deleted_at = timezone.now()
        self.deleted_by = actor
        self.delete_reason = (reason or "").strip()
        self.save(
            update_fields=["deleted_at", "deleted_by", "delete_reason", "updated_at"],
            actor=actor,
            source=source or self.SOURCE_INTERNAL,
        )

    def restore(self, *, actor=None, source=None):
        if self.deleted_at is None:
            return

        self.deleted_at = None
        self.deleted_by = None
        self.delete_reason = ""
        self.save(
            update_fields=["deleted_at", "deleted_by", "delete_reason", "updated_at"],
            actor=actor,
            source=source or self.SOURCE_INTERNAL,
        )

    def _build_changes(self, previous):
        current_deleted_at = self.deleted_at.isoformat() if self.deleted_at else None
        previous_deleted_at = previous["deleted_at"].isoformat() if previous["deleted_at"] else None
        tracked = {
            "vulgo": (previous["vulgo"], self.vulgo),
            "attending": (previous["attending"], self.attending),
            "is_public": (previous["is_public"], self.is_public),
            "values": (previous["values"], self.values),
            "deleted_at": (previous_deleted_at, current_deleted_at),
            "delete_reason": (previous["delete_reason"], self.delete_reason),
        }
        return {
            field: [old, new]
            for field, (old, new) in tracked.items()
            if old != new
        }


class SignupAuditLog(models.Model):
    ACTION_CREATED = "created"
    ACTION_UPDATED = "updated"
    ACTION_HIDDEN = "hidden"
    ACTION_SHOWN = "shown"
    ACTION_DELETED = "deleted"
    ACTION_RESTORED = "restored"
    ACTION_PURGED = "purged"

    SOURCE_PUBLIC_FORM = EventSignup.SOURCE_PUBLIC_FORM
    SOURCE_INTERNAL = EventSignup.SOURCE_INTERNAL
    SOURCE_API = EventSignup.SOURCE_API

    ACTION_CHOICES = [
        (ACTION_CREATED, "Erstellt"),
        (ACTION_UPDATED, "Aktualisiert"),
        (ACTION_HIDDEN, "Verborgen"),
        (ACTION_SHOWN, "Sichtbar gemacht"),
        (ACTION_DELETED, "Gelöscht"),
        (ACTION_RESTORED, "Wiederhergestellt"),
        (ACTION_PURGED, "Endgültig gelöscht"),
    ]
    SOURCE_CHOICES = [
        (SOURCE_PUBLIC_FORM, "Web-Formular"),
        (SOURCE_INTERNAL, "Intern"),
        (SOURCE_API, "API"),
    ]

    signup_id = models.PositiveBigIntegerField(db_index=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="signup_audit_logs")
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"Signup {self.signup_id}: {self.action}"

    @classmethod
    def record(cls, *, signup, event, action, actor, source, changes):
        if signup.pk is None:
            return None
        return cls.objects.create(
            signup_id=signup.pk,
            event=event,
            action=action,
            actor=actor,
            source=source,
            changes=changes or {},
        )


class EventCalendarTombstone(models.Model):
    calendar_uid = models.CharField(max_length=255, unique=True)
    title = models.CharField(max_length=200, blank=True)
    start = models.DateTimeField(null=True, blank=True)
    end = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    was_public = models.BooleanField(default=False)
    calendar_sequence = models.PositiveIntegerField(default=0)
    cancelled_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-cancelled_at", "-pk"]

    def __str__(self):
        return self.calendar_uid
