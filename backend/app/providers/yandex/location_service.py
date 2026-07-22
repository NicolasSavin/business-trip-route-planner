from app.providers.yandex.client import YandexRaspClient
from app.providers.yandex.config import YandexRaspConfiguration
from app.providers.yandex.resolver import YandexLocationResolver

_config = YandexRaspConfiguration.from_env()
_client = YandexRaspClient(_config)
yandex_location_resolver = YandexLocationResolver(directory_loader=_client.stations_list)
