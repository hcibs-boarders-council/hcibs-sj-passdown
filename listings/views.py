from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import ClaimForm, ItemForm
from .models import Claim, Item, ItemPhoto


def home(request):
    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()

    items = (
        Item.objects
        .filter(status=Item.Status.AVAILABLE)
        .select_related('owner')
        .prefetch_related(
            Prefetch(
                'photos',
                queryset=ItemPhoto.objects.order_by('position', 'id'),
            ),
        )
        .order_by('-created_at')
    )

    if query:
        items = items.filter(
            Q(title__icontains=query) | Q(description__icontains=query)
        )

    valid_categories = {value for value, _ in Item.Category.choices}

    if category in valid_categories:
        items = items.filter(category=category)
    else:
        category = ''

    return render(
        request,
        'accounts/home.html',
        {
            'items': items,
            'query': query,
            'category': category,
            'categories': Item.Category.choices,
        },
    )


@login_required(login_url='login')
@require_http_methods(['GET', 'POST'])
def create_item(request):
    if request.method == 'POST':
        form = ItemForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                item = form.save(commit=False)
                item.owner = request.user
                item.save()

                for position, photo in enumerate(form.cleaned_data['photos']):
                    ItemPhoto.objects.create(
                        item=item,
                        image=photo,
                        position=position,
                    )
            return redirect('home')
    else:
        form = ItemForm()

    return render(request, 'listings/item_form.html', {'form': form})


@login_required(login_url='login')
@require_http_methods(['GET'])
def item_detail(request, pk):
    item = get_object_or_404(
        Item.objects
        .filter(status=Item.Status.AVAILABLE)
        .select_related('owner')
        .prefetch_related(
            Prefetch('photos', queryset=ItemPhoto.objects.order_by('position', 'id')),
        ),
        pk=pk,
    )
    photos = list(item.photos.all())

    if not photos:
        raise Http404('This listing has no photos.')

    active_photo = photos[0]
    selected_photo_id = request.GET.get('photo')
    if selected_photo_id and selected_photo_id.isdigit():
        active_photo = next(
            (photo for photo in photos if photo.pk == int(selected_photo_id)),
            active_photo,
        )

    active_index = photos.index(active_photo)
    previous_photo = photos[active_index - 1] if active_index else None
    next_photo = photos[active_index + 1] if active_index + 1 < len(photos) else None
    existing_claim = Claim.objects.filter(item=item, claimant=request.user).first()

    return render(
        request,
        'listings/item_detail.html',
        {
            'item': item,
            'photos': photos,
            'active_photo': active_photo,
            'previous_photo': previous_photo,
            'next_photo': next_photo,
            'claim_form': ClaimForm(),
            'existing_claim': existing_claim,
        },
    )

@login_required(login_url='login')
@require_http_methods(['POST'])
def create_claim(request, pk):
    item = get_object_or_404(
        Item.objects.select_related('owner'),
        pk=pk,
    )

    if item.owner_id == request.user.id:
        messages.error(request, 'You cannot claim your own item.')
        return redirect('item_detail', pk=item.pk)

    form = ClaimForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Please check your claim note and try again.')
        return redirect('item_detail', pk=item.pk)

    if item.status != Item.Status.AVAILABLE:
        messages.error(request, 'This item is no longer available to claim.')
        return redirect('home')

    with transaction.atomic():
        # Lock the item first so concurrent claim requests are serialised.
        item = Item.objects.select_for_update().get(pk=item.pk)

        if item.status != Item.Status.AVAILABLE:
            messages.error(request, 'This item is no longer available to claim.')
            return redirect('home')

        # Check the latest claim state after acquiring the lock.
        existing_claim = Claim.objects.filter(
            item=item,
            claimant=request.user,
        ).first()

        if existing_claim and existing_claim.status != Claim.Status.CANCELLED:
            messages.info(request, 'You already have a claim for this item.')
            return redirect('my_claims')

        if existing_claim:
            claim = existing_claim
            claim.note = form.cleaned_data['note']
            claim.status = Claim.Status.PENDING
            claim.decided_at = None
        else:
            claim = form.save(commit=False)
            claim.item = item
            claim.claimant = request.user

        try:
            claim.full_clean()
        except ValidationError as error:
            messages.error(request, '; '.join(error.messages))
            return redirect('item_detail', pk=item.pk)

        claim.save()

    messages.success(request, 'Your claim was sent to the item owner.')
    return redirect('my_claims')

@login_required(login_url='login')
@require_http_methods(['POST'])
def update_claim(request, pk, action):
    with transaction.atomic():
        claim = get_object_or_404(
            Claim.objects
            .select_for_update()
            .select_related('item', 'item__owner', 'claimant'),
            pk=pk,
        )
        item = Item.objects.select_for_update().get(pk=claim.item_id)
        now = timezone.now()

        if action == 'cancel':
            if not claim.can_cancel(request.user):
                messages.error(request, 'You cannot cancel this claim.')
                return redirect('my_claims')

            was_approved = claim.status == Claim.Status.APPROVED
            claim.status = Claim.Status.CANCELLED
            claim.decided_at = now
            claim.save(update_fields=['status', 'decided_at', 'updated_at'])

            if was_approved and item.status == Item.Status.RESERVED:
                item.status = Item.Status.AVAILABLE
                item.save(update_fields=['status', 'updated_at'])

            messages.success(request, 'Your claim was cancelled.')
            return redirect('my_claims')

        if action == 'approve':
            if not claim.can_approve(request.user):
                messages.error(request, 'You cannot approve this claim.')
                return redirect('my_posts')
            if item.status != Item.Status.AVAILABLE:
                messages.error(request, 'This item is no longer available.')
                return redirect('my_posts')

            claim.status = Claim.Status.APPROVED
            claim.decided_at = now
            claim.save(update_fields=['status', 'decided_at', 'updated_at'])

            item.status = Item.Status.RESERVED
            item.save(update_fields=['status', 'updated_at'])

            Claim.objects.filter(
                item=item,
                status=Claim.Status.PENDING,
            ).exclude(pk=claim.pk).update(
                status=Claim.Status.DECLINED,
                decided_at=now,
            )
            messages.success(request, 'Claim approved and item reserved.')
            return redirect('my_posts')

        if action == 'decline':
            if not claim.can_decline(request.user):
                messages.error(request, 'You cannot decline this claim.')
                return redirect('my_posts')

            claim.status = Claim.Status.DECLINED
            claim.decided_at = now
            claim.save(update_fields=['status', 'decided_at', 'updated_at'])
            messages.success(request, 'Claim declined.')
            return redirect('my_posts')

        if action == 'complete':
            if not claim.can_mark_completed(request.user):
                messages.error(request, 'You cannot complete this claim.')
                return redirect('my_posts')

            claim.status = Claim.Status.COMPLETED
            claim.decided_at = now
            claim.save(update_fields=['status', 'decided_at', 'updated_at'])

            item.status = Item.Status.PASSED_ON
            item.save(update_fields=['status', 'updated_at'])
            messages.success(request, 'Item marked as passed on.')
            return redirect('my_posts')

    messages.error(request, 'Unknown claim action.')
    return redirect('home')