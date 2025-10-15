class NotFoundError(Exception):
    """Resource not found"""
    pass

class InvalidOperation(Exception):
    """An invalid operation was requsted to be performed."""
    pass

class ValueError(Exception):
    """Unexpected value error."""
    pass
    
class AuthenticationError(Exception):
    """Error when trying to connect apex proxy api."""
    pass