from django.contrib import admin

from .models import Claim, Item, ItemPhoto


class ItemPhotoInline(admin.TabularInline):
    model = ItemPhoto
    extra = 0
    min_num = 1
    max_num = 5
    validate_min = True
    validate_max = True
    fields = ['image', 'position', 'created_at']
    readonly_fields = ['created_at']


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ['title', 'owner', 'category', 'status', 'created_at']
    list_filter = ['category', 'status']
    search_fields = ['title', 'description', 'owner__username']
    inlines = [ItemPhotoInline]


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ['item', 'claimant', 'status', 'created_at', 'decided_at']
    list_filter = ['status', 'created_at']
    search_fields = ['item__title', 'claimant__username', 'note']
    autocomplete_fields = ['item', 'claimant']
    readonly_fields = ['created_at', 'updated_at', 'decided_at']
