def is_platform_super_admin(user):
    """The platform grant is explicit and valid only for active, signed-in superusers."""
    return bool(user.is_authenticated and user.is_active and user.is_superuser)
