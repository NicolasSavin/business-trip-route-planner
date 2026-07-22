class YandexRaspError(Exception):
    """Base recoverable Yandex Rasp API error."""

    code = "provider_request_failed"

    def __init__(self, message: str, *, query: str | None = None, diagnostics: dict | None = None):
        super().__init__(message)
        self.message = message
        self.query = query
        self.diagnostics = diagnostics or {}

    def to_error(self) -> dict:
        payload = {"code": self.code, "message": self.message}
        if self.query is not None:
            payload["query"] = self.query
        if self.diagnostics:
            payload["details"] = self.diagnostics
        return payload


class YandexRaspAuthError(YandexRaspError):
    """API key is missing, invalid, or rejected by Yandex."""


class YandexRaspRateLimitError(YandexRaspError):
    """Yandex Rasp API returned HTTP 429."""


class YandexRaspServerError(YandexRaspError):
    """Yandex Rasp API returned a server-side error."""


class YandexRaspTimeoutError(YandexRaspError):
    """Yandex Rasp API request timed out."""


class YandexRaspUnknownCityError(YandexRaspError):
    """City cannot be resolved to an official Yandex settlement or station code."""

    code = "unknown_location"


class YandexRaspInvalidResponseError(YandexRaspError):
    """Yandex Rasp API response cannot be mapped safely."""

    code = "invalid_provider_response"


class YandexRaspEmptyResponseError(YandexRaspError):
    """Yandex Rasp API returned no usable search segments."""

    code = "empty_provider_response"

