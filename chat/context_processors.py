
from django.db.models import Count, F, FilteredRelation, Q

from .models import Conversation


def chat_unread_count(request):
    if not request.user.is_authenticated:
        return {"chat_unread_count": 0}

    user = request.user

    unread_count = (
        Conversation.objects
        .for_user(user)
        .annotate(
            current_read_state=FilteredRelation(
                "read_states",
                condition=Q(read_states__user=user),
            ),
        )
        .aggregate(
            unread_count=Count(
                "messages",
                filter=(
                    ~Q(messages__sender=user)
                    & (
                        Q(
                            messages__created_at__gt=F(
                                "current_read_state__last_read_at"
                            )
                        )
                        | Q(current_read_state__isnull=True)
                    )
                ),
                distinct=True,
            ),
        )["unread_count"]
    )

    return {"chat_unread_count": unread_count or 0}