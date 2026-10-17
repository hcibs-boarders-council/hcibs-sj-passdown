
import json
import os

import firebase_admin
from firebase_admin import credentials
from django.conf import settings


def get_firebase_app():
    try:
        return firebase_admin.get_app()
    except ValueError:
        # Production: load credentials from Render's environment.
        service_account_json = os.environ.get(
            "FIREBASE_SERVICE_ACCOUNT_JSON"
        )

        if service_account_json:
            service_account_info = json.loads(service_account_json)
            certificate = credentials.Certificate(
                service_account_info
            )
        else:
            # Local development: use the private JSON file.
            credentials_file = settings.FIREBASE_SERVICE_ACCOUNT_KEY

            if not credentials_file.is_file():
                raise FileNotFoundError(
                    "Firebase service-account credentials are missing."
                )

            certificate = credentials.Certificate(
                str(credentials_file)
            )

        return firebase_admin.initialize_app(certificate)
