from .models import FolderScope


def is_document_admin(user):
    return user.is_authenticated and user.profile.can_manage_roles()


def can_view_document(user, document):
    if not user.is_authenticated:
        return False
    if document.visibility == FolderScope.SENSITIVE:
        return user.profile.can_access_sensitive_documents()
    return True


def can_download_document(user, document):
    return can_view_document(user, document)


def can_edit_document(user, document):
    if not can_view_document(user, document):
        return False
    if is_document_admin(user):
        return True
    return document.uploaded_by_id == user.id


def can_delete_document(user, document):
    return can_edit_document(user, document)
