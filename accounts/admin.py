from django.contrib import admin

from .forms import AdminProfileForm, MemorialEntryForm
from .models import MemorialEntry, Profile, Role


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("display_label", "code")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    form = AdminProfileForm
    list_display = ("full_name_with_title", "user", "membership_status_label", "entry_term_display", "exit_term_display")
    list_filter = ("entry_semester", "exit_semester", "roles")
    search_fields = ("first_name", "last_name", "vulgo", "academic_title", "degree_program", "user__username")
    filter_horizontal = ("roles",)
    readonly_fields = ("membership_status_label", "membership_period_display")
    fieldsets = (
        ("Profil", {"fields": ("user", "photo", "first_name", "last_name", "vulgo")}),
        ("Studium und Verbindung", {"fields": ("academic_title", "degree_program", "birth_date")}),
        (
            "Mitgliedschaft",
            {
                "fields": (
                    "entry_year",
                    "entry_semester",
                    "exit_year",
                    "exit_semester",
                    "death_date",
                    "confirm_death_date_effects",
                    "membership_status_label",
                    "membership_period_display",
                )
            },
        ),
        ("Rollen", {"fields": ("roles",)}),
    )


@admin.register(MemorialEntry)
class MemorialEntryAdmin(admin.ModelAdmin):
    form = MemorialEntryForm
    list_display = (
        "display_name",
        "death_display",
        "is_published",
        "is_honorary_member",
        "legacy_marker",
        "is_profile_generated",
    )
    list_filter = ("is_published", "is_honorary_member", "is_profile_generated")
    search_fields = ("display_name", "legacy_marker", "member_profile__first_name", "member_profile__last_name", "member_profile__vulgo")
