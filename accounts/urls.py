
from django.urls import path
from . import views


urlpatterns = [
    # Authentication
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),
    path('register/', views.register, name='register'),
    path('verify-email/', views.verify_email, name='verify_email'),

    # Firebase Authentication
    path(
        'firebase/complete-registration/',
        views.firebase_complete_registration,
        name='firebase_complete_registration',
    ),
    path(
        'firebase/login/',
        views.firebase_login,
        name='firebase_login',
    ),

    # Push Notifications
    path(
        'notifications/save-token/',
        views.save_push_notification_token,
        name='save_push_notification_token',
    ),

    # Website Pages
    path('our-vision/', views.our_vision, name='our_vision'),
    path('account/', views.account_detail, name='account_detail'),
    path('account/posts/', views.my_posts, name='my_posts'),
    path('account/claims/', views.my_claims, name='my_claims'),
]
