from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied


class RoleAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    required_roles = ()
    allow_admin = True

    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if self.allow_admin and user.profile.has_role("ADMIN"):
            return True
        return user.profile.has_any_role(*self.required_roles)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied
        return super().handle_no_permission()
