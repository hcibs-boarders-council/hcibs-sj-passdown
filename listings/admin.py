
from django.contrib import admin
from django.utils import timezone

from .models import Claim, Item, ItemPhoto


class ItemPhotoInline(admin.TabularInline):
    model = ItemPhoto
    extra = 0
    can_delete = False
    max_num = 5
    fields = ['image', 'position', 'created_at']
    readonly_fields = ['image', 'position', 'created_at']

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = [
        'title',
        'owner',
        'category',
        'status',
        'moderation_status',
        'created_at',
    ]
    list_filter = ['moderation_status', 'category', 'status']
    search_fields = ['title', 'description', 'owner__username']
    inlines = [ItemPhotoInline]

    # Prevent normal admin editing of listing content.
    readonly_fields = [
        'owner',
        'title',
        'description',
        'category',
        'status',
        'created_at',
        'updated_at',
        'moderation_status',
        'moderation_reviewed_at',
        'moderation_reviewed_by',
        'moderation_rejection_reason',
    ]

    fields = [
        'owner',
        'title',
        'description',
        'category',
        'status',
        'moderation_status',
        'moderation_reviewed_at',
        'moderation_reviewed_by',
        'moderation_rejection_reason',
        'created_at',
        'updated_at',
    ]

    actions = ['approve_listings', 'reject_listings']

    @admin.action(description='Approve selected listings')
    def approve_listings(self, request, queryset):
        updated = queryset.exclude(
            moderation_status=Item.ModerationStatus.APPROVED,
        ).update(
            moderation_status=Item.ModerationStatus.APPROVED,
            moderation_reviewed_at=timezone.now(),
            moderation_reviewed_by=request.user,
            moderation_rejection_reason='',
        )
        self.message_user(request, f'{updated} listing(s) approved.')

    @admin.action(description='Reject selected listings')
    def reject_listings(self, request, queryset):
        updated = queryset.exclude(
            moderation_status=Item.ModerationStatus.REJECTED,
        ).update(
            moderation_status=Item.ModerationStatus.REJECTED,
            moderation_reviewed_at=timezone.now(),
            moderation_reviewed_by=request.user,
        )
        self.message_user(request, f'{updated} listing(s) rejected.')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ['item', 'claimant', 'status', 'created_at', 'decided_at']
    list_filter = ['status', 'created_at']
    search_fields = ['item__title', 'claimant__username', 'note']
    autocomplete_fields = ['item', 'claimant']
    readonly_fields = ['created_at', 'updated_at', 'decided_at']

