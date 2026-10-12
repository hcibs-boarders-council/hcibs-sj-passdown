from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),
    path('register/', views.register, name='register'),
    path('our-vision/', views.our_vision, name='our_vision'),
    path('account/', views.account_detail, name='account_detail'),
    path('account/posts/', views.my_posts, name='my_posts'),
    path('account/claims/', views.my_claims, name='my_claims'),
]
