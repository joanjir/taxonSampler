from django.shortcuts import render


# ────────────────────────────────────────────
# Custom error handlers (used when DEBUG=False)
# ────────────────────────────────────────────

def custom_400_view(request, exception=None):
    """400 Bad Request."""
    return render(request, "400.html", status=400)


def custom_403_view(request, exception=None):
    """403 Forbidden."""
    return render(request, "403.html", status=403)


def custom_404_view(request, exception=None):
    """404 Not Found."""
    return render(request, "404.html", status=404)


def custom_500_view(request):
    """500 Internal Server Error.

    NOTE: The 500 handler receives only `request` (no `exception`).
    The 500.html template uses NO Django template tags because the
    template engine itself may be broken during a 500 error.
    """
    return render(request, "500.html", status=500)
