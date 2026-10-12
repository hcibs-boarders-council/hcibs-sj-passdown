from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import ItemPhoto


@receiver(post_delete, sender=ItemPhoto)
def delete_item_photo_file(sender, instance, **kwargs):
    if not instance.image or not instance.image.name:
        return

    storage = instance.image.storage
    name = instance.image.name
    transaction.on_commit(lambda: storage.delete(name))
