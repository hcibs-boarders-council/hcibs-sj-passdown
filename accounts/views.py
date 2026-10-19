
import json
import logging
import secrets
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    login as auth_login,
    logout as auth_logout,
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import (
    Case,
    Count,
    Exists,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    Value,
    When,
)
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from firebase_admin import auth as firebase_auth

from .firebase_admin import get_firebase_app
from .forms import AccountDetailsForm
from .models import (
    EmailVerification,
    FirebaseAccount,
    PushNotificationToken,
)
from chat.models import Conversation
from listings.models import Claim, Item, ItemPhoto


logger = logging.getLogger(__name__)

VERIFICATION_EXPIRY_MINUTES = 10
MAX_VERIFICATION_ATTEMPTS = 5


def our_vision(request):
    return render(request, 'accounts/our_vision.html')


def login(request):
    if request.method == 'POST':
        username = User.normalize_username(
            request.POST.get('username', '').strip()
        )
        password = request.POST.get('password', '')
        next_url = request.POST.get('next', '')
        errors = []

        if not username or not password:
            errors.append('Enter both your username and password.')
        else:
            user = authenticate(
                request,
                username=username,
                password=password,
            )

            if user is None:
                errors.append(
                    'We could not log you in with that username and password. '
                    'If you have not verified your email, please verify it first.'
                )
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
            {
                'errors': errors,
                'username': username,
                'next': next_url,
            },
        )

    return render(
        request,
        'accounts/login.html',
        {'next': request.GET.get('next', '')},
    )


def logout(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    auth_logout(request)
    return redirect('home')


def _username_errors(username):
    """Validate usernames and prevent case-insensitive duplicates."""
    field = User._meta.get_field('username')

    if len(username) > field.max_length:
        return [
            f'Usernames can be at most {field.max_length} characters.'
        ]

    try:
        for validator in field.validators:
            validator(username)
    except ValidationError:
        return [
            'Usernames can only contain letters, numbers and @ . + - _ '
            '(no spaces).'
        ]

    if User.objects.filter(username__iexact=username).exists():
        return ['That username is already taken.']

    return []


def _issue_verification_code(user):
    """Legacy Django verification-code flow."""
    code = f'{secrets.randbelow(1_000_000):06d}'

    EmailVerification.objects.update_or_create(
        user=user,
        defaults={
            'code_hash': make_password(code),
            'expires_at': timezone.now() + timedelta(
                minutes=VERIFICATION_EXPIRY_MINUTES
            ),
            'attempts': 0,
        },
    )

    send_mail(
        subject='Your SJ Passdown verification code',
        message=(
            f'Hi {user.username},\n\n'
            f'Your SJ Passdown verification code is: {code}\n\n'
            f'This code expires in {VERIFICATION_EXPIRY_MINUTES} minutes.'
        ),
        from_email='SJ Passdown <noreply@sjpassdown.local>',
        recipient_list=[user.email],
        fail_silently=False,
        using='default',
    )


def register(request):
    """Legacy Django registration flow."""
    if request.method == 'POST':
        username = User.normalize_username(
            request.POST.get('username', '').strip()
        )
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password_confirmation = request.POST.get(
            'password_confirmation', ''
        )
        errors = []

        if not username:
            errors.append('Username is required.')

        if not email:
            errors.append('Email is required.')

        if not password:
            errors.append('Password is required.')

        if not password_confirmation:
            errors.append('Password confirmation is required.')

        if (
            password
            and password_confirmation
            and password != password_confirmation
        ):
            errors.append('Passwords do not match.')

        if username:
            errors.extend(_username_errors(username))

        if email:
            try:
                validate_email(email)
            except ValidationError:
                errors.append('Enter a valid email address.')

        if (
            password
            and password_confirmation
            and password == password_confirmation
        ):
            try:
                validate_password(password, User(username=username))
            except ValidationError as error:
                password_error_messages = {
                    'password_too_similar':
                        'Password must not be too similar to your username.',
                    'password_too_short':
                        'Password must be at least 8 characters long.',
                    'password_too_common':
                        'Choose a less common password that is harder to guess.',
                    'password_entirely_numeric':
                        'Password cannot contain only numbers. Include letters or symbols.',
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
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=password,
                        is_active=False,
                    )
            except IntegrityError:
                errors.append('That username is already taken.')
            else:
                request.session['pending_verification_user_id'] = user.pk

                try:
                    _issue_verification_code(user)
                except Exception:
                    logger.exception(
                        'Failed to send legacy verification email.'
                    )
                    messages.error(
                        request,
                        'Your account was created, but the verification email '
                        'could not be generated. Please request a new code '
                        'on the verification page.',
                    )
                else:
                    messages.success(
                        request,
                        'Your verification code has been generated. '
                        'Check the VS Code terminal.',
                    )

                return redirect('verify_email')

        return render(
            request,
            'accounts/register.html',
            {
                'errors': errors,
                'username': username,
                'email': email,
            },
        )

    return render(request, 'accounts/register.html')


def verify_email(request):
    """Display the Firebase email verification page."""
    return render(request, 'accounts/verify_email.html')


@require_POST
def firebase_complete_registration(request):
    """Verify a Firebase ID token and connect it to a Django account."""
    if not request.content_type or not request.content_type.startswith(
        'application/json'
    ):
        return JsonResponse(
            {'error': 'Expected a JSON request.'},
            status=400,
        )

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {'error': 'Invalid request.'},
            status=400,
        )

    if not isinstance(data, dict):
        return JsonResponse(
            {'error': 'Invalid request.'},
            status=400,
        )

    id_token = data.get('id_token', '')
    username = User.normalize_username(
        str(data.get('username', '')).strip()
    )

    if not isinstance(id_token, str) or not id_token or not username:
        return JsonResponse(
            {'error': 'Missing authentication token or username.'},
            status=400,
        )

    try:
        app = get_firebase_app()

        decoded_token = firebase_auth.verify_id_token(
            id_token,
            app=app,
            check_revoked=True,
        )

        firebase_user = firebase_auth.get_user(
            decoded_token['uid'],
            app=app,
        )
    except Exception:
        logger.exception(
            'Firebase registration authentication failed.'
        )
        return JsonResponse(
            {'error': 'Firebase authentication failed. Please try again.'},
            status=401,
        )

    if not firebase_user.email or not firebase_user.email_verified:
        return JsonResponse(
            {'error': 'Please verify your email before continuing.'},
            status=403,
        )

    email = firebase_user.email.strip()

    try:
        with transaction.atomic():
            linked_account = (
                FirebaseAccount.objects
                .select_related('user')
                .filter(firebase_uid=firebase_user.uid)
                .first()
            )

            if linked_account:
                django_user = linked_account.user

                if not django_user.is_active:
                    return JsonResponse(
                        {'error': 'This account is inactive.'},
                        status=403,
                    )
            else:
                username_errors = _username_errors(username)

                if username_errors:
                    return JsonResponse(
                        {'error': username_errors[0]},
                        status=409,
                    )

                if User.objects.filter(email__iexact=email).exists():
                    return JsonResponse(
                        {
                            'error': (
                                'An account with this email already exists. '
                                'Please contact the site administrator.'
                            )
                        },
                        status=409,
                    )

                django_user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=None,
                    is_active=True,
                )

                django_user.set_unusable_password()
                django_user.save(update_fields=['password'])

                FirebaseAccount.objects.create(
                    user=django_user,
                    firebase_uid=firebase_user.uid,
                )

    except IntegrityError:
        logger.exception(
            'Database error while completing Firebase registration.'
        )
        return JsonResponse(
            {'error': 'The account could not be created. Please try again.'},
            status=409,
        )

    auth_login(
        request,
        django_user,
        backend='django.contrib.auth.backends.ModelBackend',
    )

    return JsonResponse({
        'ok': True,
        'redirect': '/',
    })


@require_POST
def firebase_login(request):
    """Verify Firebase credentials and create a Django login session."""
    if not request.content_type or not request.content_type.startswith(
        'application/json'
    ):
        return JsonResponse(
            {'ok': False, 'error': 'Expected a JSON request.'},
            status=400,
        )

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {'ok': False, 'error': 'Invalid request.'},
            status=400,
        )

    if not isinstance(data, dict):
        return JsonResponse(
            {'ok': False, 'error': 'Invalid request.'},
            status=400,
        )

    id_token = data.get('idToken')

    if not isinstance(id_token, str) or not id_token.strip():
        return JsonResponse(
            {'ok': False, 'error': 'Please log in again.'},
            status=400,
        )

    try:
        app = get_firebase_app()
        decoded_token = firebase_auth.verify_id_token(
            id_token,
            app=app,
            check_revoked=True,
        )
    except Exception as exc:
        logger.exception(
            'Firebase login token verification failed (%s): %s',
            type(exc).__name__,
            exc,
        )
        return JsonResponse(
            {
                'ok': False,
                'error': (
                    'Your login session is invalid or expired. Please try again.'
                ),
            },
            status=401,
        )

    if not decoded_token.get('email_verified', False):
        return JsonResponse(
            {
                'ok': False,
                'error': 'Please verify your email before logging in.',
            },
            status=403,
        )

    firebase_uid = decoded_token.get('uid')

    if not firebase_uid:
        return JsonResponse(
            {'ok': False, 'error': 'Invalid Firebase account.'},
            status=401,
        )

    try:
        firebase_account = (
            FirebaseAccount.objects
            .select_related('user')
            .get(firebase_uid=firebase_uid)
        )
    except FirebaseAccount.DoesNotExist:
        return JsonResponse(
            {
                'ok': False,
                'error': (
                    'No SJ Passdown account is linked to this Firebase account. '
                    'Please register first.'
                ),
            },
            status=404,
        )

    django_user = firebase_account.user

    if not django_user.is_active:
        return JsonResponse(
            {'ok': False, 'error': 'This account is inactive.'},
            status=403,
        )

    next_url = data.get('next', '/')

    if (
        not isinstance(next_url, str)
        or not url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        next_url = '/'

    auth_login(
        request,
        django_user,
        backend='django.contrib.auth.backends.ModelBackend',
    )

    return JsonResponse({
        'ok': True,
        'redirect': next_url,
    })


@login_required(login_url='login')
def account_detail(request):
    if request.method == 'POST':
        form = AccountDetailsForm(request.POST, instance=request.user)

        if form.is_valid():
            form.save()
            messages.success(
                request,
                'Your account details were updated.',
            )
            return redirect('account_detail')
    else:
        form = AccountDetailsForm(instance=request.user)

    return render(
        request,
        'accounts/account_detail.html',
        {'form': form},
    )


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

    return render(
        request,
        'accounts/my_posts.html',
        {'page_obj': page},
    )


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

    return render(
        request,
        'accounts/my_claims.html',
        {'page_obj': page},
    )


@login_required(login_url='login')
@require_POST
def save_push_notification_token(request):
    """Save the current user's Firebase Cloud Messaging device token."""
    if not request.content_type or not request.content_type.startswith(
        'application/json'
    ):
        return JsonResponse(
            {'ok': False, 'error': 'Expected a JSON request.'},
            status=400,
        )

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {'ok': False, 'error': 'Invalid request.'},
            status=400,
        )

    if not isinstance(data, dict):
        return JsonResponse(
            {'ok': False, 'error': 'Invalid request.'},
            status=400,
        )

    token = data.get('token')

    if not isinstance(token, str):
        return JsonResponse(
            {'ok': False, 'error': 'Missing notification token.'},
            status=400,
        )

    token = token.strip()

    if not token or len(token) > 4096:
        return JsonResponse(
            {'ok': False, 'error': 'Invalid notification token.'},
            status=400,
        )

    PushNotificationToken.objects.update_or_create(
        token=token,
        defaults={'user': request.user},
    )

    return JsonResponse({'ok': True})
