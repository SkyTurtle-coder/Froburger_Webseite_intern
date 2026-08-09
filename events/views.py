from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.utils import timezone
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from core.permissions import RoleAccessMixin

from .forms import EventForm, EventSignupColumnFormSet, EventSignupManageForm, EventSignupPublicForm
from .models import Event, EventSignup


class EventListView(RoleAccessMixin, ListView):
    model = Event
    template_name = "events/event_list.html"
    context_object_name = "events"
    required_roles = ("WEB_X",)

    def get_queryset(self):
        queryset = Event.objects.order_by("start", "title")
        query = self.request.GET.get("q", "").strip()
        visibility = self.request.GET.get("visibility", "").strip()
        timing = self.request.GET.get("timing", "").strip()
        status = self.request.GET.get("status", "").strip()
        now = timezone.now()

        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(slug__icontains=query)
                | Q(short_description__icontains=query)
                | Q(location__icontains=query)
            )
        if visibility == "public":
            queryset = queryset.filter(is_public=True)
        elif visibility == "internal":
            queryset = queryset.filter(is_public=False)
        if timing == "upcoming":
            queryset = queryset.filter(end__gte=now)
        elif timing == "past":
            queryset = queryset.filter(end__lt=now)
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        context["active_query"] = self.request.GET.get("q", "").strip()
        context["active_visibility"] = self.request.GET.get("visibility", "").strip()
        context["active_timing"] = self.request.GET.get("timing", "").strip()
        context["active_status"] = self.request.GET.get("status", "").strip()
        context["status_options"] = Event.STATUS_CHOICES
        context["total_events_count"] = Event.objects.count()
        context["public_events_count"] = Event.objects.filter(is_public=True).count()
        context["upcoming_events_count"] = Event.objects.filter(end__gte=now).count()
        context["past_events_count"] = Event.objects.filter(end__lt=now).count()
        return context


class EventCreateView(RoleAccessMixin, CreateView):
    model = Event
    form_class = EventForm
    template_name = "events/event_form.html"
    required_roles = ("WEB_X",)
    success_url = reverse_lazy("event-list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "column_formset" not in context:
            context["column_formset"] = EventSignupColumnFormSet(
                self.request.POST or None,
                instance=self.object,
                prefix="columns",
            )
        context["managed_signup_forms"] = []
        return context

    def form_valid(self, form):
        context = self.get_context_data(form=form)
        column_formset = context["column_formset"]
        if not column_formset.is_valid():
            return self.form_invalid(form)

        self.object = form.save()
        column_formset.instance = self.object
        column_formset.save()
        messages.success(self.request, "Anlass wurde erstellt.")
        return HttpResponseRedirect(self.get_success_url())


class EventUpdateView(RoleAccessMixin, UpdateView):
    model = Event
    form_class = EventForm
    template_name = "events/event_form.html"
    required_roles = ("WEB_X",)
    success_url = reverse_lazy("event-list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "column_formset" not in context:
            context["column_formset"] = EventSignupColumnFormSet(
                self.request.POST or None,
                instance=self.object,
                prefix="columns",
            )
        if "managed_signup_forms" not in context:
            context["managed_signup_forms"] = self._build_manage_signup_forms()
        context["signup_count"] = self.object.signups.count()
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.POST.get("action") == "manage-signups":
            return self._handle_signup_management()
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        context = self.get_context_data(form=form)
        column_formset = context["column_formset"]
        if not column_formset.is_valid():
            return self.form_invalid(form)

        self.object = form.save()
        column_formset.instance = self.object
        column_formset.save()
        messages.success(self.request, "Anlass wurde aktualisiert.")
        return HttpResponseRedirect(self.get_success_url())

    def _build_manage_signup_forms(self):
        return [
            EventSignupManageForm(
                self.request.POST or None,
                event=self.object,
                signup=signup,
                prefix=f"signup-{signup.pk}",
            )
            for signup in self.object.signups.order_by("created_at", "pk")
        ]

    def _handle_signup_management(self):
        signup_forms = self._build_manage_signup_forms()
        column_formset = EventSignupColumnFormSet(instance=self.object, prefix="columns")
        if not signup_forms:
            messages.info(self.request, "Es sind noch keine Einschreibungen vorhanden.")
            return redirect("event-edit", pk=self.object.pk)

        forms_valid = True
        for form in signup_forms:
            if not form.is_valid():
                forms_valid = False
        if forms_valid:
            normalized_seen = set()
            duplicate_detected = False
            for form in signup_forms:
                if form.cleaned_data.get("delete"):
                    continue
                normalized_vulgo = EventSignup.normalize_vulgo(form.cleaned_data["vulgo"])
                if normalized_vulgo in normalized_seen:
                    form.add_error("vulgo", "Dieses Vulgo ist in der Liste bereits vorhanden.")
                    duplicate_detected = True
                normalized_seen.add(normalized_vulgo)

            if not duplicate_detected:
                try:
                    with transaction.atomic():
                        for form in signup_forms:
                            signup = form.signup
                            if form.cleaned_data.get("delete"):
                                signup.delete()
                                continue
                            signup.vulgo = form.cleaned_data["vulgo"]
                            signup.attending = form.cleaned_data["attending"]
                            signup.values = form.build_values()
                            signup.save()
                except (IntegrityError, ValidationError):
                    signup_forms[0].add_error(None, "Die Einschreibungen konnten nicht gespeichert werden.")
                else:
                    messages.success(self.request, "Einschreibungen wurden aktualisiert.")
                    return redirect("event-edit", pk=self.object.pk)

        context = self.get_context_data(
            form=self.form_class(instance=self.object),
            column_formset=column_formset,
            managed_signup_forms=signup_forms,
        )
        return self.render_to_response(context)


class EventDeleteView(RoleAccessMixin, DeleteView):
    model = Event
    template_name = "events/event_confirm_delete.html"
    required_roles = ("WEB_X",)
    success_url = reverse_lazy("event-list")

    def form_valid(self, form):
        messages.success(self.request, "Anlass wurde gelöscht.")
        return super().form_valid(form)


class PublicEventDetailView(DetailView):
    model = Event
    template_name = "events/public_event_detail.html"
    context_object_name = "event"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        return Event.objects.filter(is_public=True).prefetch_related("signup_columns", "signups").order_by("start", "title")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = EventSignupPublicForm(request.POST, event=self.object)
        if form.is_valid():
            normalized_vulgo = EventSignup.normalize_vulgo(form.cleaned_data["vulgo"])
            if EventSignup.objects.filter(event=self.object, normalized_vulgo=normalized_vulgo).exists():
                form.add_error("vulgo", "Dieses Vulgo ist für diesen Anlass bereits eingetragen.")
            elif self._signup_throttled():
                form.add_error(None, "Bitte warte kurz, bevor du es erneut versuchst.")

        if form.is_valid():
            try:
                signup = EventSignup(
                    event=self.object,
                    vulgo=form.cleaned_data["vulgo"],
                    attending=form.cleaned_data["attending"],
                    values=form.build_values(),
                )
                signup.save()
            except IntegrityError:
                form.add_error("vulgo", "Dieses Vulgo ist für diesen Anlass bereits eingetragen.")
            except ValidationError as exc:
                form.add_error(None, exc.message if hasattr(exc, "message") else "Die Anmeldung konnte nicht gespeichert werden.")
            else:
                self._mark_signup_attempt()
                messages.success(request, "Du wurdest für diesen Anlass eingetragen.")
                return HttpResponseRedirect(self.request.path)

        context = self.get_context_data(signup_form=form)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        signups = list(self.object.signups.order_by("created_at", "pk"))
        signup_columns = list(self.object.active_signup_columns())
        signup_rows = [
            {
                "signup": signup,
                "extra_values": [signup.values.get(column.key, "") or "-" for column in signup_columns],
            }
            for signup in signups
        ]
        context["canonical_source_url"] = self.object.public_source_url
        context["wordpress_fallback_url"] = self.object.wordpress_fallback_url
        context["signup_form"] = kwargs.get("signup_form") or EventSignupPublicForm(event=self.object)
        context["signup_columns"] = signup_columns
        context["signups"] = signups
        context["signup_rows"] = signup_rows
        return context

    def _client_ip(self):
        forwarded_for = self.request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return self.request.META.get("REMOTE_ADDR", "unknown")

    def _signup_cache_key(self):
        return f"public-event-signup:{self.object.pk}:{self._client_ip()}"

    def _signup_throttled(self):
        return bool(cache.get(self._signup_cache_key()))

    def _mark_signup_attempt(self):
        cache.set(self._signup_cache_key(), True, timeout=10)
