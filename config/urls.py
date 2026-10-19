
"""
URL configuration for config project.
"""

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.views.generic import TemplateView


urlpatterns = [
    path('admin/', admin.site.urls),

    path('chat/', include('chat.urls')),

    # Firebase Cloud Messaging service worker
    path(
        'firebase-messaging-sw.js',
        TemplateView.as_view(
            template_name='firebase-messaging-sw.js',
            content_type='application/javascript',
        ),
        name='firebase_messaging_sw',
    ),

    # Listings and account URLs
    path('', include('listings.urls')),
    path('', include('accounts.urls')),
]


# Serve media and static files during local development.
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
    urlpatterns += staticfiles_urlpatterns()
