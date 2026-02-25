from django.shortcuts import render


def custom_404_view(request, exception=None):
    """Render consistent 404 page using project layout.

    This is intended to be registered as the project's handler404.
    Note: Django only uses handler404 when DEBUG is False. For preview
    during development use the `preview_404` view below.
    """
    return render(request, "404.html", status=404)


def preview_404(request):
    """Render the 404 template for preview in development.

    This route can be mounted only when DEBUG is True so developers can
    preview the page without toggling settings.
    """
    return render(request, "404.html", status=404)
