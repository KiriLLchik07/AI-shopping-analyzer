# Базовый класс Исключений приложения
class ApplicationError(Exception):
    default_detail = "Application error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


# Основные категории ошибок
# 404
class NotFoundError(ApplicationError):
    default_detail = "Resource not found"


# 409
class ConflictError(ApplicationError):
    default_detail = "Resource conflict"


# 401
class AuthenticationError(ApplicationError):
    default_detail = "Authentication required"


# 400
class BusinessRuleError(ApplicationError):
    default_detail = "Operation is not allowed"


# 429
class TooManyRequestsError(ApplicationError):
    default_detail = "Too many requests"

    def __init__(
        self,
        retry_after: int,
        detail: str | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(detail)


# Далее идут кастомные ошибки, каждая из которых принадлежит конкретному блоку
class ReceiptNotFoundError(NotFoundError):
    default_detail = "Receipt not found"


class InvalidCredentialsError(AuthenticationError):
    default_detail = "Invalid email or password"


class SessionRequiredError(AuthenticationError):
    default_detail = "Authentication required"


class InvalidSessionError(AuthenticationError):
    default_detail = "Session is invalid"


class TooManyLoginAttemptsError(TooManyRequestsError):
    default_detail = "Too many login attempts"


class EmailAlreadyExistsError(ConflictError):
    default_detail = "User with this email already exists"


class InvalidCurrentPasswordError(BusinessRuleError):
    default_detail = "Current password is incorrect"


class PasswordReuseError(BusinessRuleError):
    default_detail = "New password must differ from current password"


class ReceiptItemNotFounded(NotFoundError):
    default_detail = "Receipt item not founded"
