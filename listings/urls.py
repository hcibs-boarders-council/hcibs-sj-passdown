
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('items/create/', views.create_item, name='item_create'),
    path('items/<int:pk>/', views.item_detail, name='item_detail'),
    path('items/<int:pk>/claim/', views.create_claim, name='claim_create'),
    path('items/<int:pk>/delete/', views.delete_item, name='item_delete'),
    path('claims/<int:pk>/<str:action>/', views.update_claim, name='claim_update'),
]
