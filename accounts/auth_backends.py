from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User

from .models import Profile


class EmailOrVulgoBackend(ModelBackend):
    @staticmethod
    def normalize_identifier(value):
        return " ".join((value or "").strip().split()).casefold()

    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = username or kwargs.get(User.USERNAME_FIELD) or ""
        normalized_identifier = self.normalize_identifier(identifier)
        if not normalized_identifier or password is None:
            return None

        if "@" in normalized_identifier:
            users = list(User.objects.exclude(email="").filter(email__iexact=identifier.strip())[:2])
            if len(users) == 1:
                user = users[0]
                if user.check_password(password) and self.user_can_authenticate(user):
                    return user
                return None
            if len(users) > 1:
                return None

        matches = []
        for profile in Profile.objects.select_related("user").exclude(vulgo=""):
            if self.normalize_identifier(profile.vulgo) == normalized_identifier:
                matches.append(profile)
                if len(matches) > 1:
                    break
        if len(matches) != 1:
            return None

        user = matches[0].user
        if not user.check_password(password):
            return None
        if not self.user_can_authenticate(user):
            return None
        return user
