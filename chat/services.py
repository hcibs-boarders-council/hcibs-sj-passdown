"""Chat domain logic shared by the HTTP views and the WebSocket consumers.

Everything that creates messages, marks conversations read, counts unread
messages, or publishes real-time events lives here, so the form fallback and
the WebSocket path behave identically.

Channel-layer groups (all on the project's existing Redis channel layer):
    chat_conversation_<id>  sockets showing that conversation (ChatConsumer)
    chat_user_<id>          every page a user has open (NotificationConsumer)
    session_user_<id>       both socket types; used to close sockets on logout
"""
import logging
import re

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError, transaction
from django.db.models import Count, F, FilteredRelation, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from .models import Conversation, Message

logger = logging.getLogger(__name__)

PREVIEW_LENGTH = 140
CLIENT_MESSAGE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


class ClientMessageIdConflict(Exception):
    """A client message id was reused for a different conversation."""


def conversation_group(conversation_id):
    return f'chat_conversation_{conversation_id}'


def user_group(user_id):
    return f'chat_user_{user_id}'


def session_group(user_id):
    return f'session_user_{user_id}'


def is_valid_client_message_id(value):
    return isinstance(value, str) and bool(CLIENT_MESSAGE_ID_RE.match(value))


def display_time(value):
    """Format a stored (UTC) timestamp in the site's local time zone."""
    return date_format(timezone.localtime(value), 'j M, g:i a')


def serialize_message(message, sender_name=None):
    return {
        'id': message.pk,
        'conversation_id': message.conversation_id,
        'sender_id': message.sender_id,
        'sender_name': sender_name or message.sender.get_username(),
        'body': message.body,
        'created_at': message.created_at.isoformat(),
        'display_time': display_time(message.created_at),
    }


# Unread counts -----------------------------------------------------------

def _unread_filter(user):
    return (
        ~Q(messages__sender=user)
        & (
            Q(messages__created_at__gt=F('current_read_state__last_read_at'))
            | Q(current_read_state__isnull=True)
        )
    )


def _with_read_state(queryset, user):
    return queryset.annotate(
        current_read_state=FilteredRelation(
            'read_states',
            condition=Q(read_states__user=user),
        ),
    )


def unread_total(user):
    """Unread messages across all of the user's conversations (one query)."""
    if not user.is_authenticated:
        return 0
    result = _with_read_state(Conversation.objects.for_user(user), user).aggregate(
        unread_count=Count('messages', filter=_unread_filter(user), distinct=True),
    )
    return result['unread_count'] or 0


def unread_counts(user, conversation_id=None):
    """Total unread plus the unread count for one conversation (one query)."""
    per_conversation = dict(
        _with_read_state(Conversation.objects.for_user(user), user)
        .annotate(unread=Count('messages', filter=_unread_filter(user), distinct=True))
        .values_list('pk', 'unread')
    )
    return {
        'total': sum(per_conversation.values()),
        'conversation': per_conversation.get(conversation_id, 0),
    }


def annotate_unread(queryset, user):
    return _with_read_state(queryset, user).annotate(
        unread_count=Count('messages', filter=_unread_filter(user), distinct=True),
    )


# Writing -------------------------------------------------------------------

def create_message(*, conversation, sender, body, client_message_id=None):
    """Store a message (or return the one already stored for this client id).

    Returns (message, created). Retrying with the same client_message_id never
    creates a second message, even if two retries race each other.
    """
    if client_message_id:
        existing = Message.objects.filter(
            sender=sender,
            client_message_id=client_message_id,
        ).first()
        if existing is not None:
            if existing.conversation_id != conversation.pk:
                raise ClientMessageIdConflict(client_message_id)
            return existing, False

    try:
        with transaction.atomic():
            message = Message.objects.create(
                conversation=conversation,
                sender=sender,
                body=body,
                client_message_id=client_message_id or None,
            )
            Conversation.objects.filter(pk=conversation.pk).update(
                updated_at=message.created_at,
            )
            conversation.mark_read(sender, up_to=message)
    except IntegrityError:
        # Either a retry raced us to the same client id (reuse its message), or
        # something else failed — e.g. the conversation was deleted mid-send.
        existing = None
        if client_message_id:
            existing = Message.objects.filter(sender=sender, client_message_id=client_message_id).first()
        if existing is None:
            raise
        if existing.conversation_id != conversation.pk:
            raise ClientMessageIdConflict(client_message_id)
        return existing, False

    return message, True


def mark_read(conversation, user, up_to=None):
    """Mark read and return the user's fresh unread counts."""
    conversation.mark_read(user, up_to=up_to)
    return unread_counts(user, conversation.pk)


# Real-time events ---------------------------------------------------------

def message_events(message):
    """Channel-layer events for a newly stored message.

    The open conversation gets the full message. Each participant's own
    notification channel gets a preview plus *their* unread counts, so badges
    always show server-computed numbers (never client-side guesses).
    """
    conversation = (
        Conversation.objects
        .select_related('item', 'owner', 'requester')
        .get(pk=message.conversation_id)
    )
    sender_name = (
        conversation.owner.get_username()
        if message.sender_id == conversation.owner_id
        else conversation.requester.get_username()
    )
    payload = serialize_message(message, sender_name=sender_name)

    events = [(
        conversation_group(conversation.pk),
        {
            'type': 'chat.message',
            'message': payload,
            'client_message_id': message.client_message_id,
        },
    )]

    preview = {**payload, 'body': payload['body'][:PREVIEW_LENGTH]}
    for participant, counterpart in (
        (conversation.owner, conversation.requester),
        (conversation.requester, conversation.owner),
    ):
        counts = unread_counts(participant, conversation.pk)
        events.append((
            user_group(participant.pk),
            {
                'type': 'notify.message',
                'conversation_id': conversation.pk,
                'conversation_url': reverse('chat:conversation_detail', args=[conversation.pk]),
                'item_title': conversation.item.title,
                'counterpart_name': counterpart.get_username(),
                'message': preview,
                'unread_total': counts['total'],
                'conversation_unread': counts['conversation'],
            },
        ))
    return events


def read_events(conversation_id, user, counts):
    """Tell the user's other open pages/tabs that a conversation was read."""
    return [(
        user_group(user.pk),
        {
            'type': 'notify.read',
            'conversation_id': conversation_id,
            'unread_total': counts['total'],
            'conversation_unread': counts['conversation'],
        },
    )]


def send_events(events):
    """Publish events from synchronous code. Failures are logged, never raised:
    the message is already saved and clients catch up when they reconnect."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    for group, event in events:
        try:
            async_to_sync(channel_layer.group_send)(group, event)
        except Exception:
            logger.exception('Failed to publish %s to %s', event.get('type'), group)


async def asend_events(channel_layer, events):
    """Publish events from async code (consumers)."""
    for group, event in events:
        try:
            await channel_layer.group_send(group, event)
        except Exception:
            logger.exception('Failed to publish %s to %s', event.get('type'), group)


def broadcast_message_on_commit(message):
    """Publish a message once the surrounding transaction has committed."""
    def publish():
        try:
            events = message_events(message)
        except Exception:
            logger.exception('Failed to build events for chat message %s', message.pk)
            return
        send_events(events)

    transaction.on_commit(publish)


def broadcast_read_on_commit(conversation_id, user, counts):
    transaction.on_commit(lambda: send_events(read_events(conversation_id, user, counts)))


def end_session_sockets(user_id, session_key):
    """Close the WebSockets opened with a session that is logging out."""
    send_events([(
        session_group(user_id),
        {'type': 'session.ended', 'session_key': session_key},
    )])
