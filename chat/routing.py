from django.urls import path

from .consumers import ChatConsumer, NotificationConsumer

websocket_urlpatterns = [
    path(
        "ws/chat/<int:conversation_id>/",
        ChatConsumer.as_asgi(),
    ),
    path(
        "ws/notifications/",
        NotificationConsumer.as_asgi(),
    ),
]
