from __future__ import annotations

from datetime import date

import httpx

from app.domain import TransportType
from app.providers.yandex.config import YandexRaspConfiguration
from app.providers.yandex.exceptions import YandexRaspAuthError, YandexRaspRateLimitError, YandexRaspServerError, YandexRaspTimeoutError


YANDEX_TRANSPORT_TYPES = {
    TransportType.TRAIN: "train",
    TransportType.BUS: "bus",
}
SUBURBAN_TRANSPORT_TYPE = "suburban"


class YandexRaspClient:
    def __init__(self, config: YandexRaspConfiguration, http_client: httpx.Client | None = None):
        self.config = config
        self._client = http_client or httpx.Client(base_url=config.base_url, timeout=config.timeout_seconds)
        self.last_status_code: int | None = None

    def search(self, *, origin_code: str, destination_code: str, departure_date: date, allowed_transport: list[TransportType], transfers: bool = True) -> dict:
        transport_types = [YANDEX_TRANSPORT_TYPES[item] for item in allowed_transport if item in YANDEX_TRANSPORT_TYPES]
        if TransportType.TRAIN in allowed_transport:
            transport_types.append(SUBURBAN_TRANSPORT_TYPE)
        return self._get("/search/", params={
            "from": origin_code,
            "to": destination_code,
            "date": departure_date.isoformat(),
            "transport_types": ",".join(dict.fromkeys(transport_types)),
            "transfers": "true" if transfers else "false",
            "format": "json",
            "lang": "ru_RU",
            "page": 1,
        })

    def stations_list(self) -> dict:
        return self._get("/stations_list/", params={"format": "json", "lang": "ru_RU"})

    def _get(self, path: str, params: dict) -> dict:
        if not self.config.api_key:
            raise YandexRaspAuthError("YANDEX_RASP_API_KEY is not configured")
        try:
            response = self._client.get(path, params={"apikey": self.config.api_key, **params})
            self.last_status_code = response.status_code
        except httpx.TimeoutException as exc:
            raise YandexRaspTimeoutError("Yandex Rasp API timeout") from exc
        if response.status_code in {401, 403}:
            raise YandexRaspAuthError("Yandex Rasp API rejected API key")
        if response.status_code == 429:
            raise YandexRaspRateLimitError("Yandex Rasp API rate limit exceeded")
        if response.status_code >= 500:
            raise YandexRaspServerError(f"Yandex Rasp API server error: {response.status_code}")
        response.raise_for_status()
        return response.json()
