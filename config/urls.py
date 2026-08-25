from django.conf import settings
from django.contrib import admin
from django.conf.urls.static import static
from django.contrib.auth.views import (
    LogoutView,
    PasswordChangeDoneView,
    PasswordChangeView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.urls import include, path, reverse_lazy

from accounts.forms import PortalPasswordResetForm
from accounts.public_views import v1_public_members_api
from accounts.views import PortalLoginView
from core.views import DashboardView, healthcheck_view
from events.public_views import (
    legacy_upcoming_events_api,
    private_calendar_feed,
    public_calendar_feed,
    public_event_calendar,
    v1_calendar_feed,
    v1_event_detail_api,
    v1_event_signup_api,
    v1_past_events_api,
    v1_upcoming_events_api,
)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthcheck_view, name="healthcheck"),
    path("api/public/events/upcoming/", legacy_upcoming_events_api, name="api-public-events-upcoming"),
    path("api/v1/public/events/upcoming/", v1_upcoming_events_api, name="api-v1-events-upcoming"),
    path("api/v1/public/events/past/", v1_past_events_api, name="api-v1-events-past"),
    path("api/v1/public/events/calendar.ics", v1_calendar_feed, name="api-v1-events-calendar"),
    path("calendar/public/events.ics", public_calendar_feed, name="public-calendar-feed"),
    path("calendar/public/events/<slug:slug>.ics", public_event_calendar, name="public-event-calendar"),
    path("calendar/private/<str:token>.ics", private_calendar_feed, name="private-calendar-feed"),
    path("api/v1/public/events/<slug:slug>/", v1_event_detail_api, name="api-v1-event-detail"),
    path("api/v1/public/events/<slug:slug>/signup/", v1_event_signup_api, name="api-v1-event-signup"),
    path("api/v1/public/members/", v1_public_members_api, name="api-v1-public-members"),
    path("accounts/login/", PortalLoginView.as_view(), name="login"),
    path("accounts/logout/", LogoutView.as_view(), name="logout"),
    path(
        "accounts/password_reset/",
        PasswordResetView.as_view(
            form_class=PortalPasswordResetForm,
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.txt",
            subject_template_name="registration/password_reset_subject.txt",
            success_url=reverse_lazy("password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "accounts/password_reset/done/",
        PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "accounts/reset/<uidb64>/<token>/",
        PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "accounts/reset/done/",
        PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    path("accounts/password_change/", PasswordChangeView.as_view(), name="password_change"),
    path("accounts/password_change/done/", PasswordChangeDoneView.as_view(), name="password_change_done"),
    # SEC-007 follow-up: the original password-reset URLs were removed while
    # the flow was half-wired (no templates, no tested mail configuration).
    # These routes are now reintroduced explicitly with project templates,
    # mail settings and reset throttling instead of enabling the whole
    # django.contrib.auth.urls bundle wholesale.
    path("accounts/", include("accounts.urls")),
    path("anlaesse/", include("events.urls")),
    path("dokumente/", include("documents.urls")),
    path("", DashboardView.as_view(), name="dashboard"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
