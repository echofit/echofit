from contextvars import ContextVar

# Stores the ID of the user performing the current operation.
# Default is "default" for local stdio usage.
# For authenticated remote usage, this will be set to the user's email or hash.
current_user_id = ContextVar("current_user_id", default="default")
