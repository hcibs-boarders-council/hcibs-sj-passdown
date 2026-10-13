from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from listings.models import Claim, Item

from . import services
from .forms import MessageForm
from .models import Conversation, Message


@login_required(login_url='login')
@require_http_methods(['GET'])
def conversation_list(request):
    latest = Message.objects.filter(conversation=OuterRef('pk')).order_by('-created_at', '-pk')
    conversations = (
        services.annotate_unread(
            Conversation.objects
            .for_user(request.user)
            .select_related('item', 'owner', 'requester'),
            request.user,
        )
        # The latest message for the preview, without loading whole histories.
        .annotate(
            latest_body=Subquery(latest.values('body')[:1]),
            latest_sender_id=Subquery(latest.values('sender_id')[:1]),
            latest_created_at=Subquery(latest.values('created_at')[:1]),
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
        # Used when the WebSocket is unavailable: chat.js posts here with
        # "Accept: application/json" and gets the stored message back; without
        # JavaScript it is an ordinary form post followed by a redirect.
        wants_json = _wants_json(request)
        form = MessageForm(request.POST)
        client_message_id = request.POST.get('client_message_id') or None
        if not services.is_valid_client_message_id(client_message_id):
            client_message_id = None

        if form.is_valid():
            try:
                message, created = services.create_message(
                    conversation=conversation,
                    sender=request.user,
                    body=form.cleaned_data['body'],
                    client_message_id=client_message_id,
                )
            except services.ClientMessageIdConflict:
                message, created = services.create_message(
                    conversation=conversation,
                    sender=request.user,
                    body=form.cleaned_data['body'],
                )
            if created:
                services.broadcast_message_on_commit(message)

            if wants_json:
                return JsonResponse(
                    {
                        'message': services.serialize_message(
                            message,
                            sender_name=request.user.get_username(),
                        ),
                        'client_message_id': message.client_message_id,
                    },
                    status=201 if created else 200,
                )
            return redirect(
                'chat:conversation_detail',
                pk=conversation.pk,
            )

        if wants_json:
            errors = form.errors.get('body') or ['Enter a valid message.']
            return JsonResponse({'error': errors[0]}, status=400)
    else:
        form = MessageForm()

    chat_messages = list(
        conversation.messages
        .select_related('sender')
        .order_by('created_at', 'id')
    )

    latest_message = chat_messages[-1] if chat_messages else None
    if latest_message is not None:
        # Only what is rendered on this page counts as read.
        counts = services.mark_read(conversation, request.user, up_to=latest_message)
        services.broadcast_read_on_commit(conversation.pk, request.user, counts)

    other_participant = conversation.other_participant(request.user)

    return render(
        request,
        'chat/conversation_detail.html',
        {
            'conversation': conversation,
            'chat_messages': chat_messages,
            'latest_message_id': latest_message.pk if latest_message else 0,
            'other_participant': other_participant,
            'is_owner': conversation.owner_id == request.user.id,
            'item_photo': conversation.item.photos.order_by('position', 'id').first(),
            'form': form,
        },
    )


def _wants_json(request):
    return request.headers.get('Accept', '').split(',')[0].strip() == 'application/json'


def _parse_message_id(raw_value):
    if raw_value is None or raw_value == '':
        return None
    if not raw_value.isdigit() or len(raw_value) > 19:
        raise ValueError(raw_value)
    return int(raw_value)


@never_cache
@login_required(login_url='login')
@require_http_methods(['GET'])
def conversation_messages(request, pk):
    """Messages after a cursor — used to catch up after reconnecting and as a
    polling fallback while the WebSocket is unavailable."""
    conversation = get_object_or_404(
        Conversation.objects.for_user(request.user),
        pk=pk,
    )

    try:
        after_id = _parse_message_id(request.GET.get('after_id', '0')) or 0
    except ValueError:
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
        'messages': [services.serialize_message(message) for message in new_messages],
    })


@never_cache
@login_required(login_url='login')
@require_POST
def conversation_mark_read(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.for_user(request.user),
        pk=pk,
    )

    try:
        last_message_id = _parse_message_id(request.POST.get('last_message_id'))
    except ValueError:
        return JsonResponse({'error': 'Invalid message id.'}, status=400)

    messages_in_conversation = conversation.messages.order_by('-created_at', '-pk')
    if last_message_id is None:
        up_to = messages_in_conversation.first()
    else:
        up_to = messages_in_conversation.filter(pk=last_message_id).first()
        if up_to is None:
            return JsonResponse({'error': 'Unknown message.'}, status=400)

    if up_to is None:
        counts = services.unread_counts(request.user, conversation.pk)
    else:
        counts = services.mark_read(conversation, request.user, up_to=up_to)
        services.broadcast_read_on_commit(conversation.pk, request.user, counts)

    return JsonResponse({
        'status': 'ok',
        'unread_total': counts['total'],
        'conversation_unread': counts['conversation'],
    })


@never_cache
@require_GET
def unread_summary(request):
    """Unread total for badge polling when the notification socket is down.
    Answers 401 (not a login redirect) so scripts can tell the session ended."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)
    return JsonResponse({'unread_total': services.unread_total(request.user)})
