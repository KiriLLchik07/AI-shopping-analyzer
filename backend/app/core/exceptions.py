# Базовый класс Исключений приложения
class ApplicationError(Exception):
    default_detail = "Application error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


# 4 основных блока ошибок
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


# Далее идут кастомные ошибки, каждая из которых принадлежит конкретному блоку
class ReceiptNotFoundError(NotFoundError):
    default_detail = "Receipt not found"
