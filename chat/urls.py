from django.urls import path

from . import views

app_name = 'chat'

urlpatterns = [
    path('', views.conversation_list, name='conversation_list'),
    path(
        'start/<int:item_id>/',
        views.start_conversation,
        name='start_conversation',
    ),
    path(
        '<int:pk>/messages/',
        views.conversation_messages,
        name='conversation_messages',
    ),
    path(
        '<int:pk>/',
        views.conversation_detail,
        name='conversation_detail',
    ),
    path(
        '<int:pk>/mark-read/',
        views.conversation_mark_read,
        name='conversation_mark_read',
    ),
]