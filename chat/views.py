import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from listings.models import Claim, Item

from django.http import Http404, JsonResponse
from django.utils.formats import date_format
from .forms import MessageForm
from .models import Conversation, Message
from django.db.models import Count, F, FilteredRelation, Prefetch, Q

logger = logging.getLogger(__name__)


def _broadcast_message(message):
    channel_layer = get_channel_layer()

    if channel_layer is None:
        return

    event = {
        "id": message.pk,
        "sender_id": message.sender_id,
        "sender_name": message.sender.get_username(),
        "body": message.body,
        "created_at": message.created_at.isoformat(),
        "display_time": date_format(
            message.created_at,
            "j M, g:i a",
        ),
    }

    try:
        async_to_sync(channel_layer.group_send)(
            f"chat_conversation_{message.conversation_id}",
            {
                "type": "chat.message",
                "message": event,
            },
        )
    except Exception:
        logger.exception(
            "Failed to broadcast chat message %s",
            message.pk,
        )

@login_required(login_url='login')
@require_http_methods(['GET'])
def conversation_list(request):
    conversations = (
        Conversation.objects
        .for_user(request.user)
        .select_related('item', 'owner', 'requester')
        .annotate(
            current_read_state=FilteredRelation(
                'read_states',
                condition=Q(read_states__user=request.user),
            ),
        )
        .annotate(
            unread_count=Count(
                'messages',
                filter=(
                    ~Q(messages__sender=request.user)
                    & (
                        Q(
                            messages__created_at__gt=F(
                                'current_read_state__last_read_at'
                            )
                        )
                        | Q(current_read_state__isnull=True)
                    )
                ),
                distinct=True,
            ),
        )
        .prefetch_related(
            Prefetch(
                'messages',
                queryset=Message.objects.select_related('sender').order_by(
                    '-created_at', '-pk'
                ),
                to_attr='recent_messages',
            )
        )
        .order_by('-updated_at')
    )

    return render(
        request,
        'chat/conversation_list.html',
        {'conversations': conversations},
    )

@login_required(login_url='login')
@require_POST
def start_conversation(request, item_id):
    """A student opens (or reopens) a chat with an item's owner.

    Allowed while the item is available, or later if the student still has an
    active (pending/approved) claim — that is when collection gets arranged.
    """
    item = get_object_or_404(Item.objects.select_related('owner'), pk=item_id)

    if item.owner_id == request.user.id:
        messages.error(request, 'You cannot start a conversation with yourself.')
        return redirect('item_detail', pk=item.pk)

    existing = Conversation.objects.filter(item=item, requester=request.user).first()
    if existing:
        return redirect('chat:conversation_detail', pk=existing.pk)

    has_active_claim = Claim.objects.filter(
        item=item,
        claimant=request.user,
        status__in=[Claim.Status.PENDING, Claim.Status.APPROVED],
    ).exists()
    if item.status != Item.Status.AVAILABLE and not has_active_claim:
        raise Http404('This item is no longer available.')

    with transaction.atomic():
        conversation, _ = Conversation.objects.get_or_create(
            item=item,
            requester=request.user,
            defaults={'owner': item.owner},
        )

    return redirect(
        'chat:conversation_detail',
        pk=conversation.pk,
    )


@login_required(login_url='login')
@require_POST
def start_claimant_conversation(request, claim_id):
    """An item owner messages someone who claimed their item."""
    claim = get_object_or_404(
        Claim.objects.select_related('item', 'claimant'),
        pk=claim_id,
        item__owner=request.user,
    )

    if claim.status == Claim.Status.CANCELLED:
        messages.error(request, 'That claim was cancelled, so there is no one to message.')
        return redirect('my_posts')

    with transaction.atomic():
        conversation, _ = Conversation.objects.get_or_create(
            item=claim.item,
            requester=claim.claimant,
            defaults={'owner': request.user},
        )

    return redirect('chat:conversation_detail', pk=conversation.pk)


@login_required(login_url='login')
@require_http_methods(['GET', 'POST'])
def conversation_detail(request, pk):
    conversation = get_object_or_404(
        Conversation.objects
        .for_user(request.user)
        .select_related('item', 'owner', 'requester'),
        pk=pk,
    )

    if request.method == 'POST':
        form = MessageForm(request.POST)

        if form.is_valid():
            with transaction.atomic():
                message = Message.objects.create(
                    conversation=conversation,
                    sender=request.user,
                    body=form.cleaned_data['body'],
                )
                Conversation.objects.filter(pk=conversation.pk).update(
                    updated_at=timezone.now(),
                )
                conversation.mark_read(request.user)

            _broadcast_message(message)

            return redirect(
                'chat:conversation_detail',
                pk=conversation.pk,
            )
    else:
        form = MessageForm()

    conversation.mark_read(request.user)

    chat_messages = list(
        conversation.messages
        .select_related('sender')
        .order_by('created_at', 'id')
    )

    latest_message_id = chat_messages[-1].pk if chat_messages else 0

    return render(
        request,
        'chat/conversation_detail.html',
        {
            'conversation': conversation,
            'chat_messages': chat_messages,
            'latest_message_id': latest_message_id,
            'other_participant': conversation.other_participant(request.user),
            'form': form,
        },
    )


@login_required(login_url='login')
@require_http_methods(['GET'])
def conversation_messages(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.for_user(request.user),
        pk=pk,
    )

    raw_after_id = request.GET.get('after_id', '0')

    try:
        after_id = int(raw_after_id)
    except (TypeError, ValueError):
        return JsonResponse(
            {'error': 'Invalid message cursor.'},
            status=400,
        )

    if after_id < 0 or len(raw_after_id) > 19:
        return JsonResponse(
            {'error': 'Invalid message cursor.'},
            status=400,
        )

    new_messages = list(
        conversation.messages
        .filter(pk__gt=after_id)
        .select_related('sender')
        .order_by('pk')[:100]
    )

    return JsonResponse({
        'messages': [
            {
                'id': message.pk,
                'sender_id': message.sender_id,
                'sender_name': message.sender.username,
                'body': message.body,
                'created_at': message.created_at.isoformat(),
                'display_time': date_format(
                    message.created_at,
                    'j M, g:i a',
                ),
            }
            for message in new_messages
        ],
    })


@login_required(login_url='login')
@require_POST
def conversation_mark_read(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.for_user(request.user),
        pk=pk,
    )

    conversation.mark_read(request.user)

    return JsonResponse({'status': 'ok'})