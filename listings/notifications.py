
import logging
from functools import lru_cache

import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings
from django.urls import reverse

from accounts.models import PushNotificationToken
from .models import Item


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_firebase_app():
    """Initialise Firebase Admin once for this Django process."""
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    service_account_path = getattr(
        settings,
        "FIREBASE_SERVICE_ACCOUNT_KEY",
        None,
    )

    if not service_account_path:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_KEY is not configured."
        )

    credential = credentials.Certificate(str(service_account_path))

    return firebase_admin.initialize_app(credential)


def send_claim_push_notification(item_id, claimant_id):
    """
    Notify the listing owner when another user successfully claims an item.

    Failures are logged and do not undo the successful claim.
    """
    try:
        item = Item.objects.select_related("owner").get(pk=item_id)

        # Never notify the claimant about their own claim.
        if item.owner_id == claimant_id:
            return

        tokens = list(
            PushNotificationToken.objects.filter(
                user_id=item.owner_id,
            ).values_list("token", flat=True)
        )

        if not tokens:
            logger.info(
                "No push notification tokens for item owner %s.",
                item.owner_id,
            )
            return

        app = get_firebase_app()
        url = reverse("item_detail", kwargs={"pk": item.pk})

        message = messaging.MulticastMessage(
            notification=messaging.Notification(
                title="Someone claimed your item!",
                body=f'{item.title} has a new claim.',
            ),
            data={
                "url": url,
                "item_id": str(item.pk),
                "type": "listing_claim",
            },
            tokens=tokens,
        )

        response = messaging.send_each_for_multicast(
            message,
            app=app,
        )

        logger.info(
            "Claim push for item %s: %s sent, %s failed.",
            item.pk,
            response.success_count,
            response.failure_count,
        )

        # Remove expired or invalid device tokens.
        invalid_tokens = []

        for token, result in zip(tokens, response.responses):
            if not result.success and result.exception:
                error_code = getattr(
                    result.exception,
                    "code",
                    "",
                )

                if error_code in {
                    "messaging/registration-token-not-registered",
                    "messaging/invalid-registration-token",
                }:
                    invalid_tokens.append(token)

        if invalid_tokens:
            PushNotificationToken.objects.filter(
                token__in=invalid_tokens,
            ).delete()

    except Exception:
        logger.exception(
            "Could not send claim push notification for item %s.",
            item_id,
        )
