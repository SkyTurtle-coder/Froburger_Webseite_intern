import logging
import mimetypes
import json
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from .forms import DocumentEditForm, DocumentFolderForm, DocumentForm
from .models import Document, DocumentFolder, FolderScope, SpreadsheetRevision
from .policies import can_delete_document, can_download_document, can_edit_document, can_view_document
from .spreadsheets import SpreadsheetError, get_editor_data, save_editor_data

logger = logging.getLogger(__name__)


def _scope_meta(scope):
    return {
        "GENERAL": {
            "title": "Allgemeine Dokumente",
            "upload_allowed": lambda profile: True,
            "access_allowed": lambda profile: True,
        },
        "SENSITIVE": {
            "title": "Sensible Dokumente",
            "upload_allowed": lambda profile: profile.can_upload_sensitive_documents(),
            "access_allowed": lambda profile: profile.can_access_sensitive_documents(),
        },
    }[scope]


def _folder_queryset(scope):
    return list(DocumentFolder.objects.filter(scope=scope).select_related("parent").order_by("name", "pk"))


def _document_queryset(scope):
    return list(
        Document.objects.filter(visibility=scope)
        .select_related("folder", "uploaded_by__profile")
        .order_by("title", "-uploaded_at", "pk")
    )


def _decorate_document_permissions(documents, user):
    is_authenticated = user.is_authenticated
    is_admin = is_authenticated and user.profile.can_manage_roles()
    can_access_sensitive = is_authenticated and user.profile.can_access_sensitive_documents()

    for document in documents:
        document.can_view = is_authenticated and (document.visibility == FolderScope.GENERAL or can_access_sensitive)
        document.can_download = document.can_view
        document.can_edit = document.can_view and (is_admin or document.uploaded_by_id == user.id)
        document.can_delete = document.can_edit
    return documents


def _add_ancestors(folder_id, folder_by_id, visible_ids, open_ids):
    current_id = folder_id
    while current_id:
        visible_ids.add(current_id)
        open_ids.add(current_id)
        current_folder = folder_by_id[current_id]
        current_id = current_folder.parent_id


def _add_descendants(folder_id, children_by_parent, visible_ids):
    for child_id in children_by_parent.get(folder_id, []):
        if child_id in visible_ids:
            continue
        visible_ids.add(child_id)
        _add_descendants(child_id, children_by_parent, visible_ids)


def _build_document_tree(scope, query, user):
    folders = _folder_queryset(scope)
    documents = _decorate_document_permissions(_document_queryset(scope), user)
    query_lower = query.lower()
    folder_by_id = {folder.pk: folder for folder in folders}
    children_by_parent = {}
    for folder in folders:
        children_by_parent.setdefault(folder.parent_id, []).append(folder.pk)

    folder_matches = set()
    matched_subtree_folder_ids = set()
    matched_document_ids = set()
    visible_folder_ids = set()
    open_folder_ids = set()

    if query_lower:
        for folder in folders:
            if query_lower in folder.name.lower():
                folder_matches.add(folder.pk)
                matched_subtree_folder_ids.add(folder.pk)
                visible_folder_ids.add(folder.pk)
                _add_ancestors(folder.pk, folder_by_id, visible_folder_ids, open_folder_ids)
                _add_descendants(folder.pk, children_by_parent, visible_folder_ids)
                _add_descendants(folder.pk, children_by_parent, matched_subtree_folder_ids)

        for document in documents:
            haystacks = [document.title.lower(), document.description.lower(), document.file_name.lower()]
            if any(query_lower in value for value in haystacks):
                matched_document_ids.add(document.pk)
                if document.folder_id:
                    _add_ancestors(document.folder_id, folder_by_id, visible_folder_ids, open_folder_ids)
    else:
        visible_folder_ids = {folder.pk for folder in folders}

    folder_nodes = {
        folder.pk: {
            "folder": folder,
            "child_folders": [],
            "documents": [],
            "is_open": False,
            "matches_query": folder.pk in folder_matches,
            "visible": folder.pk in visible_folder_ids,
            "total_items": 0,
        }
        for folder in folders
    }

    root_folders = []
    for folder in folders:
        node = folder_nodes[folder.pk]
        if folder.parent_id and folder.parent_id in folder_nodes:
            folder_nodes[folder.parent_id]["child_folders"].append(node)
        else:
            root_folders.append(node)

    root_documents = []
    for document in documents:
        is_document_match = not query_lower or document.pk in matched_document_ids
        if query_lower and document.folder_id in matched_subtree_folder_ids:
            is_document_match = True

        if not is_document_match:
            continue

        if document.folder_id and document.folder_id in folder_nodes:
            folder_nodes[document.folder_id]["documents"].append(document)
        elif document.folder_id is None:
            root_documents.append(document)

    def finalize_node(node):
        visible_children = []
        for child in node["child_folders"]:
            finalized_child = finalize_node(child)
            if finalized_child["visible"]:
                visible_children.append(finalized_child)
        node["child_folders"] = visible_children

        if query_lower:
            node["visible"] = node["visible"] or bool(node["documents"]) or bool(node["child_folders"])
        else:
            node["visible"] = True

        node["total_items"] = len(node["documents"]) + len(node["child_folders"])
        if query_lower and node["folder"].pk in open_folder_ids:
            node["is_open"] = True
        return node

    visible_root_folders = []
    for node in root_folders:
        finalized_node = finalize_node(node)
        if finalized_node["visible"]:
            visible_root_folders.append(finalized_node)

    is_empty = not visible_root_folders and not root_documents
    return {
        "root_folders": visible_root_folders,
        "root_documents": root_documents,
        "is_empty": is_empty,
        "folder_count": len(folders),
        "document_count": len(documents),
    }


def _document_response(document, *, as_attachment):
    if not default_storage.exists(document.file.name):
        raise Http404("Die Datei wurde nicht gefunden.")

    file_name = document.file_name
    content_type, _encoding = mimetypes.guess_type(file_name)
    if document.is_pdf:
        content_type = "application/pdf"
    if content_type is None:
        content_type = "application/octet-stream"

    return FileResponse(
        default_storage.open(document.file.name, "rb"),
        as_attachment=as_attachment,
        filename=file_name,
        content_type=content_type,
    )


def _get_existing_document(pk):
    return get_object_or_404(Document.objects.select_related("folder", "uploaded_by"), pk=pk)


def _get_viewable_document(request, pk):
    document = _get_existing_document(pk)
    if not can_view_document(request.user, document):
        logger.warning("document_view_denied user=%s document=%s", request.user.id, document.pk)
        raise Http404
    return document


def _get_editable_document(request, pk):
    document = _get_existing_document(pk)
    if not can_edit_document(request.user, document):
        logger.warning("document_edit_denied user=%s document=%s", request.user.id, document.pk)
        raise Http404
    return document


def _get_deletable_document(request, pk):
    document = _get_existing_document(pk)
    if not can_delete_document(request.user, document):
        logger.warning("document_delete_denied user=%s document=%s", request.user.id, document.pk)
        raise Http404
    return document


def _delete_file_if_present(file_name):
    if not file_name:
        return
    try:
        if default_storage.exists(file_name):
            default_storage.delete(file_name)
        else:
            logger.warning("document_file_missing_on_delete file=%s", Path(file_name).name)
    except Exception:
        logger.exception("document_file_delete_failed file=%s", Path(file_name).name)


@login_required
def document_hub(request):
    profile = request.user.profile
    accessible_documents = Document.objects.general()
    if profile.can_access_sensitive_documents():
        accessible_documents = Document.objects.all()
    context = {
        "general_documents_count": Document.objects.general().count(),
        "sensitive_documents_count": Document.objects.sensitive().count() if profile.can_access_sensitive_documents() else None,
        "recent_documents": accessible_documents.select_related("folder", "uploaded_by").order_by("-uploaded_at", "title")[:5],
    }
    return render(request, "documents/document_hub.html", context)


@login_required
def document_scope_view(request, scope):
    normalized_scope = scope.upper()
    if normalized_scope not in {FolderScope.GENERAL, FolderScope.SENSITIVE}:
        raise Http404

    meta = _scope_meta(normalized_scope)
    profile = request.user.profile
    query = request.GET.get("q", "").strip()
    if not meta["access_allowed"](profile):
        raise Http404

    folder_form = DocumentFolderForm(scope=normalized_scope, prefix="folder")
    document_form = DocumentForm(scope=normalized_scope, prefix="document")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create-folder" and meta["upload_allowed"](profile):
            folder_form = DocumentFolderForm(request.POST, scope=normalized_scope, prefix="folder")
            if folder_form.is_valid():
                folder_form.save()
                messages.success(request, "Ordner wurde erstellt.")
                return redirect("document-scope", scope=normalized_scope.lower())
        elif action == "upload-document" and meta["upload_allowed"](profile):
            document_form = DocumentForm(request.POST, request.FILES, scope=normalized_scope, prefix="document")
            if document_form.is_valid():
                document = document_form.save(commit=False)
                document.uploaded_by = request.user
                document.save()
                messages.success(request, "Dokument wurde hochgeladen.")
                return redirect("document-scope", scope=normalized_scope.lower())

    tree = _build_document_tree(normalized_scope, query, request.user)
    context = {
        "scope": normalized_scope,
        "scope_label": meta["title"],
        "document_tree": tree,
        "folder_form": folder_form,
        "document_form": document_form,
        "upload_allowed": meta["upload_allowed"](profile),
        "folder_count": tree["folder_count"],
        "document_count": tree["document_count"],
        "active_query": query,
    }
    return render(request, "documents/document_scope.html", context)


@login_required
def document_edit_view(request, pk):
    document = _get_editable_document(request, pk)
    form = DocumentEditForm(instance=document, document=document)

    if request.method == "POST":
        form = DocumentEditForm(request.POST, instance=document, document=document)
        if form.is_valid():
            form.save()
            logger.info("document_edited user=%s document=%s", request.user.id, document.pk)
            messages.success(request, "Das Dokument wurde bearbeitet.")
            return redirect("document-scope", scope=document.visibility.lower())

    return render(request, "documents/document_edit.html", {"document": document, "form": form})


@login_required
def document_spreadsheet_edit_view(request, pk):
    document = _get_editable_document(request, pk)
    if not document.is_editable_spreadsheet:
        raise Http404("Für dieses Dateiformat ist kein Tabellen-Editor verfügbar.")

    if request.method == "POST":
        raw_cells = request.POST.get("cells", "")
        raw_formats = request.POST.get("formats", "[]") or "[]"
        if len(raw_cells) > 1_500_000 or len(raw_formats) > 1_500_000:
            messages.error(request, "Die Tabelle ist zu gross zum Speichern.")
            return redirect("document-spreadsheet-edit", pk=document.pk)
        try:
            cells = json.loads(raw_cells)
            formats = json.loads(raw_formats)
            revision = int(request.POST.get("revision", ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            messages.error(request, "Die Tabellenänderungen konnten nicht gelesen werden.")
            return redirect("document-spreadsheet-edit", pk=document.pk)

        saved_names = ()
        previous_file_name = ""
        expired_revisions = []
        try:
            with transaction.atomic():
                locked_document = Document.objects.select_for_update().get(pk=document.pk)
                if not can_edit_document(request.user, locked_document):
                    raise Http404
                previous_file_name = locked_document.file.name
                revision_file, new_file, next_revision = save_editor_data(
                    locked_document,
                    sheet_name=request.POST.get("sheet", ""),
                    cells=cells,
                    formats=formats,
                    expected_revision=revision,
                    user=request.user,
                )
                saved_names = (revision_file, new_file)
                SpreadsheetRevision.objects.create(
                    document=locked_document,
                    revision=next_revision,
                    file=revision_file,
                    saved_by=request.user,
                )
                locked_document.file.name = new_file
                locked_document.spreadsheet_revision = next_revision
                locked_document.save(update_fields=("file", "spreadsheet_revision"))
                expired_revisions = list(
                    locked_document.spreadsheet_revisions.order_by("-revision")[5:]
                )
                for expired in expired_revisions:
                    expired.delete()
        except SpreadsheetError as exc:
            messages.error(request, exc.messages[0])
            return redirect("document-spreadsheet-edit", pk=document.pk)
        except Exception:
            for file_name in saved_names:
                if file_name and default_storage.exists(file_name):
                    default_storage.delete(file_name)
            logger.exception("spreadsheet_save_failed user=%s document=%s", request.user.id, document.pk)
            messages.error(request, "Die Tabelle konnte nicht gespeichert werden.")
            return redirect("document-spreadsheet-edit", pk=document.pk)

        # The previous working file's content now lives on in the revision
        # backup just created above, so it would otherwise never be cleaned up.
        if previous_file_name and previous_file_name not in saved_names:
            _delete_file_if_present(previous_file_name)
        for expired in expired_revisions:
            _delete_file_if_present(expired.file.name)

        logger.info("spreadsheet_saved user=%s document=%s", request.user.id, document.pk)
        messages.success(request, "Die Tabelle wurde gespeichert. Es werden maximal fünf frühere Versionen aufbewahrt.")
        return redirect("document-spreadsheet-edit", pk=document.pk)

    try:
        editor = get_editor_data(document, request.GET.get("sheet"))
    except SpreadsheetError as exc:
        return render(request, "documents/spreadsheet_unavailable.html", {"document": document, "error": exc.messages[0]}, status=400)

    revisions = document.spreadsheet_revisions.select_related("saved_by__profile")[:5]
    return render(
        request,
        "documents/spreadsheet_edit.html",
        {"document": document, "editor": editor, "revisions": revisions},
    )


@login_required
def spreadsheet_revision_download_view(request, pk, revision):
    document = _get_viewable_document(request, pk)
    item = get_object_or_404(SpreadsheetRevision, document=document, revision=revision)
    if not default_storage.exists(item.file.name):
        raise Http404("Die Version wurde nicht gefunden.")
    return FileResponse(
        default_storage.open(item.file.name, "rb"),
        as_attachment=True,
        filename=f"{Path(document.file_name).stem}-Version-{item.revision}.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@login_required
@require_POST
def document_delete_view(request, pk):
    document = _get_deletable_document(request, pk)
    redirect_scope = document.visibility.lower()
    file_name = document.file.name

    with transaction.atomic():
        document_id = document.pk
        file_references = Document.objects.filter(file=file_name).exclude(pk=document.pk).exists()
        document.delete()
    if not file_references:
        _delete_file_if_present(file_name)

    logger.info("document_deleted user=%s document=%s", request.user.id, document_id)
    messages.success(request, "Das Dokument wurde gelöscht.")
    return redirect("document-scope", scope=redirect_scope)


@login_required
@xframe_options_sameorigin
def document_preview_view(request, pk):
    document = _get_viewable_document(request, pk)
    if not document.is_pdf:
        raise Http404("Für dieses Dateiformat ist keine Vorschau verfügbar.")
    return _document_response(document, as_attachment=False)


@login_required
def document_download_view(request, pk):
    document = _get_viewable_document(request, pk)
    if not can_download_document(request.user, document):
        logger.warning("document_download_denied user=%s document=%s", request.user.id, document.pk)
        raise Http404
    return _document_response(document, as_attachment=True)
