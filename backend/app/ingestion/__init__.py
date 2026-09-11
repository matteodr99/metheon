class IngestionError(Exception):
    """Raised by any source when its feed cannot be retrieved or is not usable.

    Shared across sources so the runner and the API can catch one type
    without knowing which source raised it.
    """
