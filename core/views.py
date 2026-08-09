from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django.views.generic import TemplateView

from accounts.models import Profile
from documents.models import Document
from events.models import Event


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = self.request.user.profile
        now = timezone.now()
        document_queryset = Document.objects.select_related("folder", "uploaded_by").order_by("-uploaded_at", "title")
        if not profile.can_access_sensitive_documents():
            document_queryset = document_queryset.filter(visibility="GENERAL")

        context["next_events"] = Event.objects.filter(end__gte=now).order_by("start", "title")[:5]
        context["recent_documents"] = document_queryset[:5]
        context["profile_obj"] = profile
        context["profile_completion"] = profile.editable_profile_completion
        context["profile_roles"] = [role.display_label for role in profile.roles.all()]
        context["show_birth_date"] = True
        context["admin_metrics"] = []
        if profile.can_manage_roles():
            context["admin_metrics"] = [
                {"label": "Mitgliederprofile", "value": Profile.objects.count()},
                {"label": "Allgemeine Dokumente", "value": Document.objects.general().count()},
                {"label": "Öffentliche Anlässe", "value": Event.objects.filter(is_public=True).count()},
                {"label": "Kommende API-Anlässe", "value": Event.objects.filter(is_public=True, end__gte=now).count()},
                {"label": "Sensible Dokumente", "value": Document.objects.sensitive().count()},
            ]
        return context


def healthcheck_view(request):
    return JsonResponse({"status": "ok"})
