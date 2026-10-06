from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods


def our_vision(request):
    return render(request, 'accounts/our_vision.html')

def login(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        errors = []

        if not username or not password:
            errors.append('Enter both your username and password.')
        else:
            user = authenticate(request, username=username, password=password)
            if user is None:
                errors.append('We could not log you in with that username and password.')
            else:
                auth_login(request, user)
                return redirect('home')

        return render(
            request,
            'accounts/login.html',
            {'errors': errors, 'username': username},
        )

    return render(request, 'accounts/login.html')


def logout(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    auth_logout(request)
    return redirect('home')

def register(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
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
        if username and User.objects.filter(username=username).exists():
            errors.append('That username is already taken.')
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
            User.objects.create_user(
                username=username,
                email=email,
                password=password,
            )
            return redirect('login')

        return render(
            request,
            'accounts/register.html',
            {'errors': errors, 'username': username, 'email': email},
        )

    return render(request, 'accounts/register.html')