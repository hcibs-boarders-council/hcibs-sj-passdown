
def moderation_context(request):
    user = request.user

    is_moderator = user.is_authenticated and (
        user.is_superuser
        or user.groups.filter(name='Listing Moderators').exists()
    )

    return {
        'is_listing_moderator': is_moderator,
    }
