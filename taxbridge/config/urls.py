"""
Root URL configuration.

URL structure:
- /admin/          - Django admin
- /api/v1/taxonomy/ - API endpoints (JSON)
- /taxonomy/        - UI pages (HTML)
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    
    # API routes (JSON responses)
    path("api/v1/taxonomy/", include("apps.taxonomy.api.urls")),
    
    # UI routes (HTML pages)
    path("taxonomy/", include("apps.taxonomy.urls")),
]

# Serve static files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
