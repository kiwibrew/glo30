class ApplicationError(Exception):
    """Base class for errors that can be translated into an API response."""

    def __init__(self, message: str, *, log_detail: str | None = None) -> None:
        super().__init__(message)
        self.log_detail = log_detail


class DuplicateUserError(ApplicationError):
    pass


class UserNotFoundError(ApplicationError):
    pass


class InvalidUserOperationError(ApplicationError):
    pass


class InvalidCredentialsError(ApplicationError):
    pass


class InactiveUserError(ApplicationError):
    pass


class InvalidPasswordResetCodeError(ApplicationError):
    pass


class RadiusLimitError(ApplicationError):
    pass


class DemCoverageError(ApplicationError):
    pass


class CopernicusTimeoutError(ApplicationError):
    pass


class CopernicusConfigurationError(ApplicationError):
    pass


class TileDownloadError(ApplicationError):
    pass


class ViewshedProcessingError(ApplicationError):
    pass
