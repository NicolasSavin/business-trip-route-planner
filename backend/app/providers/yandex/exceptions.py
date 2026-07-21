class YandexRaspError(Exception):
    """Base recoverable Yandex Rasp API error."""


class YandexRaspAuthError(YandexRaspError):
    """API key is missing, invalid, or rejected by Yandex."""


class YandexRaspRateLimitError(YandexRaspError):
    """Yandex Rasp API returned HTTP 429."""


class YandexRaspServerError(YandexRaspError):
    """Yandex Rasp API returned a server-side error."""


class YandexRaspTimeoutError(YandexRaspError):
    """Yandex Rasp API request timed out."""


class YandexRaspUnknownCityError(YandexRaspError):
    """City cannot be resolved to an official Yandex settlement code."""
