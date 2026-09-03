from pathlib import Path
import unicodedata

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView
from django.views.generic.detail import SingleObjectMixin

from core.permissions import RoleAccessMixin
from documents.models import Document, DocumentFolder, FolderScope

from .auth_forms import VulgoAuthenticationForm
from .forms import (
    AdminProfileForm,
    AdminUserPasswordResetForm,
    MemorialEntryForm,
    MemberCsvImportForm,
    PortalMemorialEntryForm,
    ProfileForm,
    UserWithProfileCreationForm,
)
from .models import MemorialEntry, Profile, Role
from .services import import_members_from_csv, memorial_queryset


def _delete_document_file_if_unused(file_name):
    if file_name and default_storage.exists(file_name):
        default_storage.delete(file_name)


def _delete_document_and_file(document):
    if not document:
        return

    file_name = document.file.name
    with transaction.atomic():
        still_referenced = Document.objects.filter(file=file_name).exclude(pk=document.pk).exists()
        document.delete()

    if not still_referenced:
        _delete_document_file_if_unused(file_name)


def _get_obituary_folder():
    """Return the shared general-document folder used for all obituaries."""
    return DocumentFolder.objects.get_or_create(
        name="Nachrufe",
        scope=FolderScope.GENERAL,
        parent=None,
    )[0]


def _build_obituary_document(user, entry, upload):
    return Document.objects.create(
        title=f"Nachruf {entry.display_name}",
        description=f"Nachruf zur Totentafel für {entry.display_name}",
        visibility=FolderScope.GENERAL,
        folder=_get_obituary_folder(),
        file=upload,
        uploaded_by=user,
    )


class PortalLoginView(LoginView):
    authentication_form = VulgoAuthenticationForm
    redirect_authenticated_user = True


class ProfileListView(RoleAccessMixin, ListView):
    model = Profile
    template_name = "accounts/profile_list.html"
    context_object_name = "profiles"
    required_roles = ("ADMIN",)

    def get_queryset(self):
        queryset = Profile.objects.select_related("user").prefetch_related("roles").order_by("last_name", "first_name")
        query = self.request.GET.get("q", "").strip()
        role_code = self.request.GET.get("role", "").strip()
        if query:
            queryset = queryset.filter(
                Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(vulgo__icontains=query)
                | Q(user__email__icontains=query)
            )
        if role_code:
            queryset = queryset.filter(roles__code=role_code)
        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["role_options"] = Role.objects.order_by("code")
        context["active_query"] = self.request.GET.get("q", "").strip()
        context["active_role"] = self.request.GET.get("role", "").strip()
        context["profile_count"] = Profile.objects.count()
        context["admin_count"] = Profile.objects.filter(roles__code="ADMIN").distinct().count()
        return context


class MemberDirectoryView(LoginRequiredMixin, ListView):
    model = Profile
    template_name = "accounts/member_directory.html"
    context_object_name = "profiles"

    SORT_FIELDS = {"name", "vulgo"}
    SORT_DIRECTIONS = {"asc", "desc"}

    @staticmethod
    def _normalize_sort_value(value):
        text = " ".join((value or "").strip().split())
        if not text:
            return ""
        replacements = (
            ("ä", "ae"),
            ("ö", "oe"),
            ("ü", "ue"),
            ("Ä", "ae"),
            ("Ö", "oe"),
            ("Ü", "ue"),
            ("ß", "ss"),
        )
        for source, target in replacements:
            text = text.replace(source, target)
        text = unicodedata.normalize("NFKD", text)
        return "".join(char for char in text if not unicodedata.combining(char)).casefold()

    def _active_sort(self):
        sort = self.request.GET.get("sort", "name").strip().lower()
        direction = self.request.GET.get("direction", "asc").strip().lower()
        if sort not in self.SORT_FIELDS:
            sort = "name"
        if direction not in self.SORT_DIRECTIONS:
            direction = "asc"
        return sort, direction

    def _sorted_profiles(self, profiles, sort, direction):
        reverse = direction == "desc"

        def name_tuple(profile):
            return (
                self._normalize_sort_value(profile.last_name),
                self._normalize_sort_value(profile.first_name),
                self._normalize_sort_value(profile.vulgo),
                profile.pk,
            )

        def vulgo_tuple(profile):
            return (
                self._normalize_sort_value(profile.vulgo),
                self._normalize_sort_value(profile.last_name),
                self._normalize_sort_value(profile.first_name),
                profile.pk,
            )

        key_fn = name_tuple if sort == "name" else vulgo_tuple
        if sort == "vulgo":
            filled = [profile for profile in profiles if self._normalize_sort_value(profile.vulgo)]
            empty = [profile for profile in profiles if not self._normalize_sort_value(profile.vulgo)]
            return sorted(filled, key=key_fn, reverse=reverse) + sorted(empty, key=name_tuple)
        return sorted(profiles, key=key_fn, reverse=reverse)

    def get_queryset(self):
        queryset = Profile.objects.filter(death_date__isnull=True).select_related("user").prefetch_related("roles")
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(vulgo__icontains=query)
                | Q(user__email__icontains=query)
            )
        sort, direction = self._active_sort()
        return self._sorted_profiles(list(queryset.distinct()), sort, direction)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_query"] = self.request.GET.get("q", "").strip()
        context["profile_count"] = Profile.objects.filter(death_date__isnull=True).count()
        sort, direction = self._active_sort()
        context["active_sort"] = sort
        context["active_direction"] = direction
        context["sort_state"] = {
            "name": {
                "aria_sort": "ascending" if sort == "name" and direction == "asc" else "descending" if sort == "name" else "none",
                "next_direction": "desc" if sort == "name" and direction == "asc" else "asc",
                "symbol": "^" if sort == "name" and direction == "asc" else "v" if sort == "name" else "<>",
            },
            "vulgo": {
                "aria_sort": "ascending" if sort == "vulgo" and direction == "asc" else "descending" if sort == "vulgo" else "none",
                "next_direction": "desc" if sort == "vulgo" and direction == "asc" else "asc",
                "symbol": "^" if sort == "vulgo" and direction == "asc" else "v" if sort == "vulgo" else "<>",
            },
        }
        return context


class UserCreateView(RoleAccessMixin, CreateView):
    form_class = UserWithProfileCreationForm
    template_name = "accounts/user_form.html"
    required_roles = ("ADMIN",)
    success_url = reverse_lazy("profile-list")

    def form_valid(self, form):
        messages.success(self.request, "Mitglied wurde angelegt.")
        return super().form_valid(form)


class MemberCsvImportView(RoleAccessMixin, FormView):
    form_class = MemberCsvImportForm
    template_name = "accounts/member_import.html"
    required_roles = ("ADMIN",)

    def form_valid(self, form):
        try:
            import_result = import_members_from_csv(form.cleaned_data["csv_file"])
        except ValueError as error:
            form.add_error("csv_file", str(error))
            return self.form_invalid(form)

        messages.success(self.request, f"{import_result.created_count} Mitglieder wurden angelegt.")
        context = self.get_context_data(form=MemberCsvImportForm())
        context["import_result"] = import_result
        return self.render_to_response(context)


class ProfileDetailView(LoginRequiredMixin, DetailView):
    model = Profile
    template_name = "accounts/profile_detail.html"
    context_object_name = "profile_obj"

    def get_queryset(self):
        user = self.request.user
        if user.profile.can_manage_roles():
            return Profile.objects.select_related("user").prefetch_related("roles")
        return Profile.objects.filter(pk=user.profile.pk).select_related("user").prefetch_related("roles")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        viewer_profile = self.request.user.profile
        context["can_manage_events"] = self.object.can_manage_events()
        context["can_access_sensitive_documents"] = self.object.can_access_sensitive_documents()
        context["is_own_profile"] = viewer_profile.pk == self.object.pk
        context["can_manage_profile"] = viewer_profile.can_manage_roles()
        context["show_birth_date"] = context["is_own_profile"] or context["can_manage_profile"]
        context["show_death_date"] = False
        context["profile_completion"] = self.object.editable_profile_completion
        context["profile_roles"] = [role.display_label for role in self.object.roles.all()]
        context["membership_status_label"] = self.object.membership_status_label
        context["password_reset_form"] = AdminUserPasswordResetForm(user=self.object.user)
        return context


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = Profile
    template_name = "accounts/profile_form.html"
    context_object_name = "profile_obj"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        profile = self.get_object()
        if not request.user.profile.can_manage_roles() and profile.pk != request.user.profile.pk:
            return redirect("profile-detail", pk=request.user.profile.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self):
        if self.request.user.profile.can_manage_roles():
            return AdminProfileForm
        return ProfileForm

    def get_success_url(self):
        return reverse_lazy("profile-detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_manage_roles"] = self.request.user.profile.can_manage_roles()
        return context

    def form_valid(self, form):
        messages.success(self.request, "Profil wurde gespeichert.")
        return super().form_valid(form)


class AdminPasswordResetView(RoleAccessMixin, SingleObjectMixin, FormView):
    model = Profile
    form_class = AdminUserPasswordResetForm
    template_name = "accounts/password_reset_form.html"
    context_object_name = "profile_obj"
    required_roles = ("ADMIN",)

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().post(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.object.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["profile_obj"] = self.object
        context["target_user"] = self.object.user
        return context

    def get_success_url(self):
        return reverse_lazy("profile-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        target_user = form.save()
        if target_user.pk == self.request.user.pk:
            update_session_auth_hash(self.request, target_user)
        messages.success(self.request, f"Passwort für {target_user.profile.display_name} wurde zurückgesetzt.")
        return redirect(self.get_success_url())


class MemorialPageView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/memorial_page.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["memorial_entries"] = memorial_queryset()
        context["can_manage_memorial_entries"] = self.request.user.profile.can_manage_roles()
        return context


class MemorialEntryCreateView(RoleAccessMixin, CreateView):
    form_class = PortalMemorialEntryForm
    template_name = "accounts/memorial_form.html"
    required_roles = ("ADMIN",)
    success_url = reverse_lazy("memorial-page")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Totentafel-Eintrag erfassen"
        context["submit_label"] = "Eintrag erstellen"
        return context

    def form_valid(self, form):
        upload = form.cleaned_data.get("obituary_upload")
        with transaction.atomic():
            self.object = form.save()
            if upload:
                self.object.obituary_document = _build_obituary_document(self.request.user, self.object, upload)
                self.object.save(update_fields=["obituary_document"])
        messages.success(self.request, "Totentafel-Eintrag wurde erstellt.")
        return redirect(self.get_success_url())


class MemorialEntryUpdateView(RoleAccessMixin, UpdateView):
    model = MemorialEntry
    form_class = PortalMemorialEntryForm
    template_name = "accounts/memorial_form.html"
    required_roles = ("ADMIN",)
    success_url = reverse_lazy("memorial-page")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Totentafel-Eintrag bearbeiten"
        context["submit_label"] = "Änderungen speichern"
        context["existing_obituary_document"] = self.object.obituary_document
        return context

    def form_valid(self, form):
        upload = form.cleaned_data.get("obituary_upload")
        remove = form.cleaned_data.get("obituary_remove")
        old_document = self.object.obituary_document
        replacement_document = None

        with transaction.atomic():
            self.object = form.save()
            if upload:
                replacement_document = _build_obituary_document(self.request.user, self.object, upload)
                self.object.obituary_document = replacement_document
                self.object.save(update_fields=["obituary_document"])
            elif remove and old_document:
                self.object.obituary_document = None
                self.object.save(update_fields=["obituary_document"])

        if upload and old_document and replacement_document and old_document.pk != replacement_document.pk:
            _delete_document_and_file(old_document)
        elif remove and old_document:
            _delete_document_and_file(old_document)

        messages.success(self.request, "Totentafel-Eintrag wurde aktualisiert.")
        return redirect(self.get_success_url())


@login_required
@require_POST
def memorial_entry_delete_view(request, pk):
    if not request.user.profile.can_manage_roles():
        raise Http404

    entry = get_object_or_404(MemorialEntry, pk=pk)
    obituary_document = entry.obituary_document

    with transaction.atomic():
        if obituary_document:
            entry.obituary_document = None
            entry.save(update_fields=["obituary_document"])
        entry.delete()

    if obituary_document:
        _delete_document_and_file(obituary_document)

    messages.success(request, "Totentafel-Eintrag wurde gelöscht.")
    return redirect("memorial-page")


def profile_photo_view(request, pk):
    if not request.user.is_authenticated:
        raise Http404
    profile = get_object_or_404(Profile, pk=pk)
    if not request.user.profile.can_manage_roles() and request.user.profile.pk != profile.pk:
        raise Http404
    if not profile.photo:
        raise Http404
    file_name = Path(profile.photo.name).name
    return FileResponse(default_storage.open(profile.photo.name, "rb"), filename=file_name)
