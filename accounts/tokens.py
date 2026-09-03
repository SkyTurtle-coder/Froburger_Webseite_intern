from django.contrib.auth.tokens import PasswordResetTokenGenerator


class AccountActivationTokenGenerator(PasswordResetTokenGenerator):
    """Password-setting token with a namespace separate from password resets."""

    key_salt = "accounts.tokens.AccountActivationTokenGenerator"


account_activation_token_generator = AccountActivationTokenGenerator()
