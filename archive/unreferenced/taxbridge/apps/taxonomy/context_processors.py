"""
Custom context processors for the taxonomy app.

Provides user role information to all templates.
"""


def user_role(request):
    """
    Add `is_admin` flag to the template context.
    A user is considered admin if they are staff or superuser.
    """
    if request.user.is_authenticated:
        return {
            "is_admin": request.user.is_staff or request.user.is_superuser,
        }
    return {
        "is_admin": False,
    }
