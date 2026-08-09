from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile
from .services import sync_profile_side_effects


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    if created:
        Profile.objects.create(
            user=instance,
            first_name=instance.first_name or instance.username,
            last_name=instance.last_name or "-",
        )


@receiver(post_save, sender=Profile)
def sync_profile_after_save(sender, instance, raw=False, **kwargs):
    if raw:
        return
    sync_profile_side_effects(instance)


@receiver(post_save, sender=User)
def save_profile(sender, instance, raw=False, created=False, **kwargs):
    if raw or created:
        return
    if hasattr(instance, "profile"):
        instance.profile.save()
