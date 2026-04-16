"""
Root URL configuration.

URL structure:
- /admin/            - Django admin
- /api/v1/taxonomy/  - API endpoints (JSON)
- /home/             - Main UI home
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include
from django.views.generic import RedirectView


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

    # API routes
    path("api/v1/taxonomy/", include("apps.taxonomy.api.urls")),

    # Redirect root / -> /home/
    path("", RedirectView.as_view(pattern_name="taxonomy:home", permanent=False)),

    # Optional: redirect old /taxonomy/ -> /home/
    path("taxonomy/", RedirectView.as_view(pattern_name="taxonomy:home", permanent=False)),

    # UI routes
    path("", include("apps.taxonomy.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

if settings.DEBUG:
    from django.views.generic import TemplateView
    urlpatterns += [
        path("__preview_400__", TemplateView.as_view(template_name="400.html"), name="preview-400"),
        path("__preview_403__", TemplateView.as_view(template_name="403.html"), name="preview-403"),
        path("__preview_404__", TemplateView.as_view(template_name="404.html"), name="preview-404"),
        path("__preview_404__/", TemplateView.as_view(template_name="404.html"), name="preview-404-slash"),
        path("__preview_500__", TemplateView.as_view(template_name="500.html"), name="preview-500"),
    ]

handler400 = "apps.taxonomy.views.custom_400_view"
handler403 = "apps.taxonomy.views.custom_403_view"
handler404 = "apps.taxonomy.views.custom_404_view"
handler500 = "apps.taxonomy.views.custom_500_view"