import logging

from django.conf import settings
from django.core.mail import send_mail

from .models import Comment

logger = logging.getLogger(__name__)


def notify_reply(comment_id, base_url):
    comment = Comment.objects.select_related("parent__author__profile", "author__profile", "issue").filter(pk=comment_id).first()
    if not comment or comment.deleted_at or not comment.parent_id:
        return
    parent = comment.parent
    recipient = parent.author
    if parent.deleted_at or recipient.pk == comment.author_id or not recipient.is_active or not recipient.email:
        return
    url = base_url.rstrip("/") + comment.get_absolute_url()
    try:
        send_mail(
            "Neue Antwort auf deinen Forum-Kommentar",
            f"Hallo {recipient.profile.vulgo}\n\n"
            f"{comment.author.profile.vulgo} hat auf deinen Kommentar zur Ausgabe «{comment.issue.title}» geantwortet.\n\n"
            f"{comment.body}\n\nAntwort im internen Bereich lesen:\n{url}\n\nAV Froburger",
            settings.DEFAULT_FROM_EMAIL,
            [recipient.email],
        )
    except Exception:
        logger.exception("Forum reply notification failed for comment %s", comment_id)
