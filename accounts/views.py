from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Prefetch, Q, Value, When
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import AccountDetailsForm
from chat.models import Conversation
from chat.services import end_session_sockets
from listings.models import Claim, Item, ItemPhoto


def our_vision(request):
    return render(request, 'accounts/our_vision.html')


def login(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        next_url = request.POST.get('next', '')
        errors = []

        if not username or not password:
            errors.append('Enter both your username and password.')
        else:
            user = authenticate(request, username=username, password=password)
            if user is None:
                errors.append('We could not log you in with that username and password.')
            else:
                auth_login(request, user)
                if url_has_allowed_host_and_scheme(
                    next_url,
                    allowed_hosts={request.get_host()},
                    require_https=request.is_secure(),
                ):
                    return redirect(next_url)
                return redirect('home')

        return render(
            request,
            'accounts/login.html',
            {'errors': errors, 'username': username, 'next': next_url},
        )

    return render(request, 'accounts/login.html', {'next': request.GET.get('next', '')})


def logout(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    user_id = request.user.pk if request.user.is_authenticated else None
    session_key = request.session.session_key

    auth_logout(request)

    if user_id is not None:
        # Close live chat/notification sockets opened with this session.
        end_session_sockets(user_id, session_key)
    return redirect('home')


def _username_errors(username):
    """Django's own username rules (length + allowed characters), with
    student-friendly messages, plus a case-insensitive uniqueness check so
    "Alex" and "alex" can't both exist."""
    field = User._meta.get_field('username')
    if len(username) > field.max_length:
        return [f'Usernames can be at most {field.max_length} characters.']
    try:
        for validator in field.validators:
            validator(username)
    except ValidationError:
        return ['Usernames can only contain letters, numbers and @ . + - _ (no spaces).']
    if User.objects.filter(username__iexact=username).exists():
        return ['That username is already taken.']
    return []


def register(request):
    if request.method == 'POST':
        username = User.normalize_username(request.POST.get('username', '').strip())
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password_confirmation = request.POST.get('password_confirmation', '')
        errors = []

        if not username:
            errors.append('Username is required.')
        if not email:
            errors.append('Email is required.')
        if not password:
            errors.append('Password is required.')
        if not password_confirmation:
            errors.append('Password confirmation is required.')
        if password and password_confirmation and password != password_confirmation:
            errors.append('Passwords do not match.')
        if username:
            errors.extend(_username_errors(username))
        if email:
            try:
                validate_email(email)
            except ValidationError:
                errors.append('Enter a valid email address.')
        if password and password_confirmation and password == password_confirmation:
            try:
                validate_password(password, User(username=username))
            except ValidationError as error:
                password_error_messages = {
                    'password_too_similar': 'Password must not be too similar to your username.',
                    'password_too_short': 'Password must be at least 8 characters long.',
                    'password_too_common': 'Choose a less common password that is harder to guess.',
                    'password_entirely_numeric': 'Password cannot contain only numbers. Include letters or symbols.',
                }
                for password_error in error.error_list:
                    errors.append(
                        password_error_messages.get(
                            password_error.code,
                            password_error.messages[0],
                        )
                    )

        if not errors:
            try:
                with transaction.atomic():
                    User.objects.create_user(
                        username=username,
                        email=email,
                        password=password,
                    )
            except IntegrityError:
                # Someone registered the same username a moment earlier.
                errors.append('That username is already taken.')
            else:
                messages.success(request, 'Your account is ready. Log in to start browsing.')
                return redirect('login')

        return render(
            request,
            'accounts/register.html',
            {'errors': errors, 'username': username, 'email': email},
        )

    return render(request, 'accounts/register.html')


@login_required(login_url='login')
def account_detail(request):
    if request.method == 'POST':
        form = AccountDetailsForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your account details were updated.')
            return redirect('account_detail')
    else:
        form = AccountDetailsForm(instance=request.user)

    return render(request, 'accounts/account_detail.html', {'form': form})


# Claims needing a decision first, then the active reservation, then history.
CLAIM_STATUS_RANK = Case(
    When(status=Claim.Status.PENDING, then=Value(0)),
    When(status=Claim.Status.APPROVED, then=Value(1)),
    When(status=Claim.Status.COMPLETED, then=Value(2)),
    default=Value(3),
    output_field=IntegerField(),
)


@login_required(login_url='login')
def my_posts(request):
    items = (
        Item.objects
        .filter(owner=request.user)
        .annotate(
            claim_total=Count('claims', distinct=True),
            pending_claim_total=Count(
                'claims',
                filter=Q(claims__status=Claim.Status.PENDING),
                distinct=True,
            ),
        )
        .prefetch_related(
            Prefetch(
                'photos',
                queryset=ItemPhoto.objects.order_by('position', 'id'),
            ),
            Prefetch(
                'claims',
                queryset=(
                    Claim.objects
                    .select_related('claimant')
                    .annotate(status_rank=CLAIM_STATUS_RANK)
                    .order_by('status_rank', '-created_at')
                ),
            ),
        )
        .order_by('-created_at')
    )
    paginator = Paginator(items, 12)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'accounts/my_posts.html', {'page_obj': page})


@login_required(login_url='login')
def my_claims(request):
    claims = (
        Claim.objects
        .filter(claimant=request.user)
        .select_related('item', 'item__owner')
        .annotate(
            has_conversation=Exists(
                Conversation.objects.filter(
                    item=OuterRef('item'),
                    requester=request.user,
                )
            ),
        )
        .prefetch_related(
            Prefetch(
                'item__photos',
                queryset=ItemPhoto.objects.order_by('position', 'id'),
            ),
        )
        .order_by('-created_at')
    )
    paginator = Paginator(claims, 12)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'accounts/my_claims.html', {'page_obj': page})
