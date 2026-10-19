
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


def item_photo_upload_to(instance, filename):
    suffix = Path(filename).suffix.lower() or '.jpg'
    return f'item_photos/{instance.item_id}/{uuid4().hex}{suffix}'


class Item(models.Model):
    class Category(models.TextChoices):
        STATIONERY = 'stationery', 'Stationery'
        BOOKS = 'books', 'Books'
        DAILY_ESSENTIALS = 'daily_essentials', 'Daily Essentials'
        CLOTHES = 'clothes', 'Clothes'
        OTHER = 'other', 'Other'

    class Status(models.TextChoices):
        AVAILABLE = 'available', 'Available'
        RESERVED = 'reserved', 'Reserved'
        PASSED_ON = 'passed_on', 'Passed on'

    class ModerationStatus(models.TextChoices):
        PENDING = 'pending', 'Pending review'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='items',
    )
    title = models.CharField(max_length=120)
    description = models.TextField(max_length=1000)
    category = models.CharField(max_length=30, choices=Category.choices)

    # Listing status: controls the item's availability and handover.
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )

    # Moderation status: controls whether the item may be published.
    moderation_status = models.CharField(
        max_length=20,
        choices=ModerationStatus.choices,
        default=ModerationStatus.PENDING,
        db_index=True,
    )
    moderation_reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    moderation_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_items',
    )
    moderation_rejection_reason = models.TextField(
        max_length=500,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounts_item'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['status', '-created_at'],
                name='item_status_created_idx',
            ),
        ]

    def __str__(self):
        return self.title


class Claim(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        DECLINED = 'declined', 'Declined'
        CANCELLED = 'cancelled', 'Cancelled'
        COMPLETED = 'completed', 'Completed'

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='claims',
    )
    claimant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='claims',
    )
    note = models.TextField(max_length=500, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['claimant', '-created_at'],
                name='claim_claimant_created_idx',
            ),
            models.Index(
                fields=['item', 'status'],
                name='claim_item_status_idx',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['item', 'claimant'],
                name='claim_unique_item_claimant',
            ),
        ]

    def __str__(self):
        return f'{self.claimant} claim for {self.item}'

    def clean(self):
        super().clean()
        if (
            self.item_id
            and self.claimant_id
            and self.item.owner_id == self.claimant_id
        ):
            raise ValidationError('You cannot claim your own item.')

    @property
    def is_active(self):
        return self.status in {
            self.Status.PENDING,
            self.Status.APPROVED,
        }

    def can_cancel(self, user):
        return (
            self.claimant_id == user.id
            and self.status in {
                self.Status.PENDING,
                self.Status.APPROVED,
            }
        )

    def can_approve(self, user):
        return (
            self.item.owner_id == user.id
            and self.status == self.Status.PENDING
        )

    def can_decline(self, user):
        return (
            self.item.owner_id == user.id
            and self.status == self.Status.PENDING
        )

    def can_mark_completed(self, user):
        return (
            self.item.owner_id == user.id
            and self.status == self.Status.APPROVED
        )

    def can_release(self, user):
        """The owner can undo an approval if the claimant never collected."""
        return (
            self.item.owner_id == user.id
            and self.status == self.Status.APPROVED
        )


class ItemPhoto(models.Model):
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='photos',
    )
    image = models.ImageField(upload_to=item_photo_upload_to)
    position = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['position', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['item', 'position'],
                name='item_photo_unique_position',
            ),
            models.CheckConstraint(
                condition=Q(position__gte=0) & Q(position__lt=5),
                name='item_photo_position_range',
            ),
        ]

    def __str__(self):
        return f'{self.item.title} photo {self.position + 1}'
