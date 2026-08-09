from accounts.roles import ROLE_LABELS
from core.public_site import get_public_site_url


def app_meta(request):
    current = getattr(getattr(request, "resolver_match", None), "url_name", "")
    navigation_section_open = current in {
        "event-list",
        "event-create",
        "event-edit",
        "event-delete",
        "member-directory",
        "memorial-page",
        "document-hub",
        "document-scope",
        "profile-detail",
        "profile-edit",
        "password_change",
        "password_change_done",
        "profile-list",
        "user-create",
    }
    return {
        "app_name": "AV Froburger Intern",
        "role_labels": ROLE_LABELS,
        "navigation_section_open": navigation_section_open,
        "public_site_url": get_public_site_url(),
    }
