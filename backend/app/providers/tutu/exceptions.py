class TutuProviderError(Exception):
    """Базовая ошибка адаптера Туту без раскрытия секретов."""


class TutuConfigurationError(TutuProviderError):
    """Конфигурация Туту неполная или официальный клиент не подключён."""
