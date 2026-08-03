"""Signal handlers for profile lifecycle and stored-file cleanup."""

from __future__ import annotations

from django.conf import settings
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from apps.accounts.models import AgentProfile, Brokerage, Role
from apps.core.storage import delete_stored_file


@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="create_agent_profile")
def create_agent_profile(sender, instance, created, **kwargs) -> None:
    """Give every new Agent an empty profile to edit.

    Without this, a freshly registered agent would have nothing at
    ``/api/agents/me/`` and the profile form would have to handle a
    create-or-update fork. Only the ``agent`` role gets one — a Brokerage
    Admin is not an agent.
    """
    if created and instance.role == Role.AGENT:
        AgentProfile.objects.get_or_create(user=instance)


def _cleanup_replaced_file(model, instance, field_name: str) -> None:
    """Delete the previous file when an image field is replaced."""
    if not instance.pk:
        return  # new row, nothing to replace

    previous = model.objects.filter(pk=instance.pk).only(field_name).first()
    if previous is None:
        return

    old_file = getattr(previous, field_name)
    new_file = getattr(instance, field_name)
    if old_file and old_file.name != getattr(new_file, "name", None):
        delete_stored_file(old_file)


@receiver(pre_save, sender=AgentProfile, dispatch_uid="agent_photo_replaced")
def agent_photo_replaced(sender, instance, **kwargs) -> None:
    _cleanup_replaced_file(AgentProfile, instance, "photo")


@receiver(pre_save, sender=Brokerage, dispatch_uid="brokerage_logo_replaced")
def brokerage_logo_replaced(sender, instance, **kwargs) -> None:
    _cleanup_replaced_file(Brokerage, instance, "logo")


@receiver(post_delete, sender=AgentProfile, dispatch_uid="agent_photo_deleted")
def agent_photo_deleted(sender, instance, **kwargs) -> None:
    delete_stored_file(instance.photo)


@receiver(post_delete, sender=Brokerage, dispatch_uid="brokerage_logo_deleted")
def brokerage_logo_deleted(sender, instance, **kwargs) -> None:
    delete_stored_file(instance.logo)
