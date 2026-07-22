from __future__ import annotations

from datetime import date

import httpx

from app.domain import TransportType
from app.providers.yandex.config import YandexRaspConfiguration
from app.providers.yandex.diagnostics import write_yandex_diagnostics
from app.providers.yandex.exceptions import (
    YandexRaspAuthError,
    YandexRaspInvalidResponseError,
    YandexRaspRateLimitError,
    YandexRaspServerError,
    YandexRaspTimeoutError,
    YandexRaspUnexpectedContentTypeError,
)


YANDEX_TRANSPORT_TYPES = {
    TransportType.TRAIN: "train",
    TransportType.BUS: "bus",
}
SUBURBAN_TRANSPORT_TYPE = "suburban"
BODY_PREVIEW_CHARS = 1000


class YandexRaspClient:
    def __init__(self, config: YandexRaspConfiguration, http_client: httpx.Client | None = None):
        self.config = config
        self._client = http_client or httpx.Client(base_url=config.base_url, timeout=config.timeout_seconds, follow_redirects=True)
        self.last_status_code: int | None = None
        self.last_response_diagnostics: dict | None = None
        self.last_request_params: dict | None = None

    def search(self, *, origin_code: str, destination_code: str, departure_date: date, allowed_transport: list[TransportType], transfers: bool = True) -> dict:
        transport_types = [YANDEX_TRANSPORT_TYPES[item] for item in allowed_transport if item in YANDEX_TRANSPORT_TYPES]
        if TransportType.TRAIN in allowed_transport:
            transport_types.append(SUBURBAN_TRANSPORT_TYPE)
        return self._get("search/", params={
            "from": origin_code,
            "to": destination_code,
            "date": departure_date.isoformat(),
            "transport_types": ",".join(dict.fromkeys(transport_types)),
            "transfers": "true" if transfers else "false",
            "format": "json",
            "lang": "ru_RU",
            "system": "yandex",
            "limit": 100,
            "offset": 0,
        })

    def stations_list(self) -> dict:
        return self._get("stations_list/", params={"format": "json", "lang": "ru_RU"})

    def _get(self, path: str, params: dict) -> dict:
        if not self.config.api_key:
            raise YandexRaspAuthError("YANDEX_RASP_API_KEY is not configured")
        request_params = {"apikey": self.config.api_key, **params}
        self.last_request_params = {**params, "apikey": "***redacted***"}
        request = self._client.build_request("GET", path, params=request_params)
        try:
            response = self._client.send(request)
            self.last_status_code = response.status_code
        except httpx.TimeoutException as exc:
            self.last_response_diagnostics = write_yandex_diagnostics(request=request, exception=exc)
            raise YandexRaspTimeoutError("Yandex Rasp API timeout", diagnostics=self.last_response_diagnostics) from exc

        self.last_response_diagnostics = write_yandex_diagnostics(request=request, response=response)
        if response.status_code in {401, 403}:
            raise YandexRaspAuthError("Yandex Rasp API rejected API key", diagnostics=self.last_response_diagnostics)
        if response.status_code == 429:
            raise YandexRaspRateLimitError("Yandex Rasp API rate limit exceeded", diagnostics=self.last_response_diagnostics)
        if response.status_code >= 500:
            raise YandexRaspServerError(f"Yandex Rasp API server error: {response.status_code}", diagnostics=self.last_response_diagnostics)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise YandexRaspInvalidResponseError("Yandex Rasp API HTTP error", diagnostics=self.last_response_diagnostics) from exc

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            diagnostics = self._unexpected_content_type_details(request, response)
            self.last_response_diagnostics = diagnostics
            raise YandexRaspUnexpectedContentTypeError(
                "Яндекс Расписания вернули ответ не в формате JSON",
                diagnostics=diagnostics,
            )

        parsed_json = None
        json_exception = None
        try:
            parsed_json = response.json()
        except Exception as exc:
            json_exception = exc
        self.last_response_diagnostics = write_yandex_diagnostics(request=request, response=response, parsed_json=parsed_json, json_exception=json_exception)
        if json_exception is not None:
            raise YandexRaspInvalidResponseError("Неожиданная структура ответа Яндекс Расписаний", diagnostics=self.last_response_diagnostics) from json_exception
        return parsed_json

    def _unexpected_content_type_details(self, request: httpx.Request, response: httpx.Response) -> dict:
        text = response.text[:BODY_PREVIEW_CHARS]
        return {
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "request_url": str(request.url).split("?", 1)[0],
            "final_response_url": str(response.url).split("?", 1)[0],
            "body_preview": text,
        }
