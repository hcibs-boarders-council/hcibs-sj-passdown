from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver

from .services import end_session_sockets


@receiver(user_logged_out)
def close_sockets_on_logout(sender, request, user, **kwargs):
    """Close the live chat/notification sockets opened with the session that is
    logging out — from the site's Logout button or the admin's. Sent before
    Django flushes the session, so the session key is still available."""
    if user is None or request is None:
        return
    session = getattr(request, 'session', None)
    end_session_sockets(user.pk, getattr(session, 'session_key', None))
