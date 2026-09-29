from functools import partial

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.decorators.clickjacking import xframe_options_sameorigin

from .forms import CommentForm, IssueForm
from .models import Comment, CommentLike, Issue
from .services import notify_reply

THREADS_PER_PAGE = 15


def can_manage(user):
    return user.profile.has_any_role("ADMIN", "WEB_X")


def check_manager(user):
    if not can_manage(user):
        raise PermissionDenied


def check_comment_owner(user, comment):
    if user.pk != comment.author_id and not can_manage(user):
        raise PermissionDenied


def remove_pdf(storage, name):
    if name and not Issue.objects.filter(pdf=name).exists():
        storage.delete(name)


@login_required
def issue_list(request):
    issues = Issue.objects.annotate(comment_count=Count("comments", filter=Q(comments__deleted_at__isnull=True)))
    page = Paginator(issues, 12).get_page(request.GET.get("page"))
    return render(request, "forum/list.html", {"page_obj": page, "can_manage": can_manage(request.user)})


def comments_for(user):
    return Comment.objects.select_related("author__profile", "parent__author__profile").annotate(
        like_count=Count("likes"),
        liked=Exists(CommentLike.objects.filter(comment_id=OuterRef("pk"), user=user)),
    ).order_by("-like_count", "-created_at", "-pk")


@login_required
def issue_detail(request, pk):
    issue = get_object_or_404(Issue, pk=pk)
    roots = comments_for(request.user).filter(issue=issue, thread__isnull=True)
    page = Paginator(roots, THREADS_PER_PAGE).get_page(request.GET.get("page"))
    threads = list(page.object_list)
    by_id = {comment.pk: comment for comment in threads}
    for comment in threads:
        comment.thread_replies = []
    for reply in comments_for(request.user).filter(thread_id__in=by_id):
        by_id[reply.thread_id].thread_replies.append(reply)
    page.object_list = threads
    return render(request, "forum/detail.html", {
        "issue": issue, "page_obj": page, "form": CommentForm(),
        "can_manage": can_manage(request.user),
        "comment_count": issue.comments.filter(deleted_at__isnull=True).count(),
    })


@login_required
def issue_edit(request, pk=None):
    check_manager(request.user)
    issue = get_object_or_404(Issue, pk=pk) if pk else Issue(author=request.user)
    old_pdf = issue.pdf.name
    form = IssueForm(request.POST if request.method == "POST" else None, request.FILES or None, instance=issue)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            issue = form.save()
            if old_pdf and old_pdf != issue.pdf.name:
                transaction.on_commit(partial(remove_pdf, issue.pdf.storage, old_pdf), robust=True)
        messages.success(request, "Forum-Ausgabe gespeichert.")
        return redirect(issue)
    return render(request, "forum/issue_form.html", {"form": form, "issue": issue})


@login_required
def issue_delete(request, pk):
    check_manager(request.user)
    issue = get_object_or_404(Issue, pk=pk)
    if request.method == "POST":
        storage, name = issue.pdf.storage, issue.pdf.name
        with transaction.atomic():
            issue.comments.update(parent=None)
            issue.delete()
            transaction.on_commit(partial(remove_pdf, storage, name), robust=True)
        messages.success(request, "Forum-Ausgabe gelöscht.")
        return redirect("forum:list")
    return render(request, "forum/confirm_delete.html", {"issue": issue})


@login_required
@never_cache
@xframe_options_sameorigin
def issue_pdf(request, pk):
    issue = get_object_or_404(Issue, pk=pk)
    try:
        stream = issue.pdf.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("PDF nicht gefunden")
    response = FileResponse(stream, content_type="application/pdf", as_attachment=request.GET.get("download") == "1",
                            filename=f"{slugify(issue.title) or 'forum'}.pdf")
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def comment_create(request, pk):
    issue = get_object_or_404(Issue, pk=pk)
    form = CommentForm(request.POST)
    parent_id = request.POST.get("parent", "")
    if parent_id and not parent_id.isdecimal():
        raise Http404
    with transaction.atomic():
        parent = get_object_or_404(Comment.objects.select_for_update(), pk=parent_id, issue=issue, deleted_at__isnull=True) if parent_id else None
        if form.is_valid():
            comment = form.save(commit=False)
            comment.author = request.user
            comment.issue = issue
            comment.parent = parent
            comment.thread_id = (parent.thread_id or parent.pk) if parent else None
            comment.save()
            if parent:
                transaction.on_commit(partial(notify_reply, comment.pk, request.build_absolute_uri("/")), robust=True)
            return redirect(comment)
    return render(request, "forum/comment_form.html", {"form": form, "issue": issue, "parent": parent}, status=400)


@login_required
def comment_link(request, pk):
    comment = get_object_or_404(Comment, pk=pk)
    root_ids = list(comments_for(request.user).filter(issue_id=comment.issue_id, thread__isnull=True).values_list("pk", flat=True))
    page = root_ids.index(comment.thread_id or comment.pk) // THREADS_PER_PAGE + 1
    return redirect(f"{comment.issue.get_absolute_url()}?page={page}#comment-{comment.pk}")


@login_required
def comment_edit(request, pk):
    with transaction.atomic():
        comment = get_object_or_404(Comment.objects.select_for_update(), pk=pk, deleted_at__isnull=True)
        check_comment_owner(request.user, comment)
        form = CommentForm(request.POST if request.method == "POST" else None, instance=comment)
        if request.method == "POST" and form.is_valid():
            if "body" in form.changed_data:
                comment = form.save(commit=False)
                comment.edited_at = timezone.now()
                comment.save(update_fields=["body", "edited_at"])
            return redirect(comment)
    return render(request, "forum/comment_form.html", {"form": form, "comment": comment, "issue": comment.issue})


@login_required
def comment_delete(request, pk):
    with transaction.atomic():
        comment = get_object_or_404(Comment.objects.select_for_update(), pk=pk, deleted_at__isnull=True)
        check_comment_owner(request.user, comment)
        if request.method == "POST":
            comment.body = ""
            comment.deleted_at = timezone.now()
            comment.save(update_fields=["body", "deleted_at"])
            comment.likes.all().delete()
            messages.success(request, "Kommentar gelöscht. Vorhandene Antworten bleiben erhalten.")
            return redirect(comment)
    return render(request, "forum/confirm_delete.html", {"comment": comment, "issue": comment.issue})


@login_required
@require_POST
def comment_like(request, pk):
    with transaction.atomic():
        comment = get_object_or_404(Comment.objects.select_for_update(), pk=pk, deleted_at__isnull=True)
        if request.POST.get("liked") == "1":
            CommentLike.objects.get_or_create(comment=comment, user=request.user)
        elif request.POST.get("liked") == "0":
            CommentLike.objects.filter(comment=comment, user=request.user).delete()
        else:
            raise Http404
    return redirect(comment)
