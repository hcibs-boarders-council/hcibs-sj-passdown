from django.conf import settings
from django.db import models


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

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='items',
    )
    title = models.CharField(max_length=120)
    description = models.TextField(max_length=1000)
    category = models.CharField(max_length=30, choices=Category.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
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