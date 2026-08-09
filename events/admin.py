from django.contrib import admin

from .models import Event, EventSignup, EventSignupColumn


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "start", "end", "status", "is_public", "show_on_homepage")
    list_filter = ("status", "is_public", "show_on_homepage")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(EventSignupColumn)
class EventSignupColumnAdmin(admin.ModelAdmin):
    list_display = ("label", "event", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("label", "event__title")


@admin.register(EventSignup)
class EventSignupAdmin(admin.ModelAdmin):
    list_display = ("vulgo", "event", "attending", "created_at", "updated_at")
    list_filter = ("attending",)
    search_fields = ("vulgo", "event__title")
