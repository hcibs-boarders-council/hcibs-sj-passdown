from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from listings.models import Item


class ConversationQuerySet(models.QuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        return self.filter(Q(owner=user) | Q(requester=user))


class Conversation(models.Model):
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='conversations',
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_conversations',
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='requested_conversations',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ConversationQuerySet.as_manager()

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['owner', '-updated_at'], name='chat_owner_updated_idx'),
            models.Index(fields=['requester', '-updated_at'], name='chat_requester_updated_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['item', 'requester'],
                name='chat_unique_item_requester',
            ),
            models.CheckConstraint(
                condition=~Q(owner=models.F('requester')),
                name='chat_owner_requester_distinct',
            ),
        ]

    def __str__(self):
        return f'{self.item} chat: {self.owner} and {self.requester}'

    def clean(self):
        super().clean()
        if self.item_id and self.owner_id and self.item.owner_id != self.owner_id:
            raise ValidationError('The conversation owner must own the item.')
        if self.owner_id and self.requester_id and self.owner_id == self.requester_id:
            raise ValidationError('You cannot start a conversation with yourself.')

    def has_participant(self, user):
        return user.is_authenticated and user.id in {self.owner_id, self.requester_id}

    def other_participant(self, user):
        if user.id == self.owner_id:
            return self.requester
        return self.owner

    def mark_read(self, user):
        if not self.has_participant(user):
            raise ValidationError('You cannot read this conversation.')
        ConversationReadState.objects.update_or_create(
            conversation=self,
            user=user,
            defaults={'last_read_at': timezone.now()},
        )

    def unread_count_for(self, user):
        if not self.has_participant(user):
            return 0
        read_state = self.read_states.filter(user=user).first()
        messages = self.messages.exclude(sender=user)
        if read_state:
            messages = messages.filter(created_at__gt=read_state.last_read_at)
        return messages.count()


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chat_messages',
    )
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['conversation', 'created_at'], name='chat_msg_convo_created_idx'),
        ]

    def __str__(self):
        return f'Message from {self.sender} in conversation {self.conversation_id}'

    def clean(self):
        super().clean()
        if self.conversation_id and self.sender_id and not self.conversation.has_participant(self.sender):
            raise ValidationError('Only conversation participants can send messages.')
        if not self.body.strip():
            raise ValidationError({'body': 'Enter a message.'})

    def save(self, *args, **kwargs):
        self.body = self.body.strip()
        super().save(*args, **kwargs)


class ConversationReadState(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='read_states',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversation_read_states',
    )
    last_read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['conversation', 'user'],
                name='chat_unique_read_state',
            ),
        ]

    def __str__(self):
        return f'{self.user} read state for conversation {self.conversation_id}'

    def clean(self):
        super().clean()
        if self.conversation_id and self.user_id and not self.conversation.has_participant(self.user):
            raise ValidationError('Only participants can have read state.')

