from django.apps import AppConfig


class ListingsConfig(AppConfig):
    name = 'listings'

    def ready(self):
        from . import signals
