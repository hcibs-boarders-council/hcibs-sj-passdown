
import json
import os

import firebase_admin
from firebase_admin import credentials
from django.conf import settings


def get_firebase_app():
    """
    Return the existing Firebase Admin app, or initialize it
    using Render's environment variable or the local JSON file.
    """
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    # On Render, read the service-account JSON from an environment variable.
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")

    if service_account_json:
        try:
            service_account_info = json.loads(service_account_json)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "FIREBASE_SERVICE_ACCOUNT_JSON contains invalid JSON."
            ) from exc

        certificate = credentials.Certificate(service_account_info)

    else:
        # Locally, use the JSON file specified in settings.py.
        credentials_file = settings.FIREBASE_SERVICE_ACCOUNT_KEY

        if not credentials_file.is_file():
            raise FileNotFoundError(
                "Firebase service-account credentials are missing. "
                "Configure FIREBASE_SERVICE_ACCOUNT_JSON on Render "
                "or provide the local service-account JSON file."
            )

        certificate = credentials.Certificate(str(credentials_file))

    return firebase_admin.initialize_app(certificate)
