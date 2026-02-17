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
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import AuthenticationForm
from django.urls import path, include


class AdminOnlyLoginView(auth_views.LoginView):
    """Only allow staff/superuser to log in."""
    def form_valid(self, form):
        user = form.get_user()
        if not (user.is_staff or user.is_superuser):
            form.add_error(None, "Solo administradores pueden iniciar sesión.")
            return self.form_invalid(form)
        return super().form_valid(form)


urlpatterns = [
    path("admin/", admin.site.urls),
    
    # Authentication
    path("accounts/login/", AdminOnlyLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    
    # API routes (JSON responses)
    path("api/v1/taxonomy/", include("apps.taxonomy.api.urls")),
    
    # UI routes (HTML pages)
    path("taxonomy/", include("apps.taxonomy.urls")),
]

# Serve static files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
