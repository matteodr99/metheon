class AIError(Exception):
    """Raised when insights cannot be produced.

    `configured` tells the API which status to answer with: False means
    there is no key and the feature is off (503), True means the upstream
    call or its output failed (502).
    """

    def __init__(self, message: str, configured: bool = True):
        super().__init__(message)
        self.configured = configured
