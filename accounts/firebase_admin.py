
import firebase_admin
from firebase_admin import credentials
from django.conf import settings


def get_firebase_app():
    try:
        return firebase_admin.get_app()
    except ValueError:
        credentials_file = settings.FIREBASE_SERVICE_ACCOUNT_KEY

        if not credentials_file.is_file():
            raise FileNotFoundError(
                "Firebase service account JSON file was not found."
            )

        certificate = credentials.Certificate(str(credentials_file))

        return firebase_admin.initialize_app(certificate)
