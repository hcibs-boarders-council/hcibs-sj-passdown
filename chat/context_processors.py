from .services import unread_total


def chat_unread_count(request):
    """Unread message total for the navbar badge (live updates come from realtime.js)."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {"chat_unread_count": 0}
    return {"chat_unread_count": unread_total(user)}
