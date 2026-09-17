from fastapi import HTTPException, status


class NotFoundError(HTTPException):
    def __init__(self, detail: str = "Not found") -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class UnauthorizedError(HTTPException):
    """Authentication failed or was not supplied.

    Distinct from ForbiddenError: 401 means "we do not know who you are",
    403 means "we know, and you may not do this".
    """

    def __init__(self, detail: str = "Not authenticated") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenError(HTTPException):
    def __init__(self, detail: str = "Forbidden") -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class ConflictError(HTTPException):
    def __init__(self, detail: str = "Conflict") -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class QuotaExceededError(HTTPException):
    def __init__(self, detail: str = "Daily upload quota exceeded") -> None:
        super().__init__(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)


class InvalidInputError(HTTPException):
    """Input passed schema validation but is still unusable — e.g. a tag label
    made only of whitespace."""

    def __init__(self, detail: str = "Invalid input") -> None:
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


class UnsupportedMediaTypeError(HTTPException):
    def __init__(self, detail: str = "Unsupported file type") -> None:
        super().__init__(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=detail)


class GoneError(HTTPException):
    """The resource existed but is permanently unavailable — e.g. a trashed
    document whose file has already been purged."""

    def __init__(self, detail: str = "No longer available") -> None:
        super().__init__(status_code=status.HTTP_410_GONE, detail=detail)


class FileTooLargeError(HTTPException):
    def __init__(self, detail: str = "File exceeds maximum allowed size") -> None:
        super().__init__(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=detail)


class FeatureNotAvailableError(HTTPException):
    def __init__(self, feature: str) -> None:
        super().__init__(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Feature '{feature}' requires an active subscription",
        )
