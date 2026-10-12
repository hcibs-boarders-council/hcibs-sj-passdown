from django.contrib import admin

from .models import Conversation, ConversationReadState, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ['sender', 'body', 'created_at']
    readonly_fields = ['created_at']


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['item', 'owner', 'requester', 'updated_at']
    search_fields = ['item__title', 'owner__username', 'requester__username']
    autocomplete_fields = ['item', 'owner', 'requester']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['conversation', 'sender', 'created_at']
    search_fields = ['body', 'sender__username', 'conversation__item__title']
    autocomplete_fields = ['conversation', 'sender']
    readonly_fields = ['created_at']


@admin.register(ConversationReadState)
class ConversationReadStateAdmin(admin.ModelAdmin):
    list_display = ['conversation', 'user', 'last_read_at']
    autocomplete_fields = ['conversation', 'user']
