# Browser Automation Infrastructure

Этот модуль подготавливает универсальную инфраструктуру браузерной автоматизации без подключения реальных сайтов, scraping, CSS-селекторов, XPath и сетевых браузерных запросов.

## Архитектура

Пакет `backend/app/browser/` содержит независимые слои:

- `BrowserConfiguration` — чтение ENV: `PLAYWRIGHT_ENABLED`, `BROWSER_HEADLESS`, `BROWSER_POOL_SIZE`, `BROWSER_TIMEOUT`, `USER_AGENT`, `PROXY`.
- `BrowserManager` — жизненный цикл драйвера: start, stop, health, restart, graceful shutdown, version detection.
- `BrowserPool` — лимитированный пул переиспользуемых `BrowserSession`.
- `BrowserSession` — безопасный интерфейс будущих браузерных действий.
- `BrowserMetrics` — счетчики active browsers, active sessions, pages opened, crashes, restarts, average lifetime.
- `BrowserAutomationProvider` — интеграционная граница для Provider Registry.

## BrowserPool

`BrowserPool` выдает сессии через `acquire()` или context manager `session()`. Количество одновременно выданных сессий ограничено `BROWSER_POOL_SIZE`. После выхода из context manager сессия автоматически закрывается и возвращается в пул для переиспользования.

## BrowserSession

`BrowserSession` содержит только контракт: `open`, `close`, `new_page`, `navigate`, `wait_ready`, `capture_html`, `capture_screenshot`, `capture_pdf`, `evaluate`, `click`, `fill`, `select`, `wait_for`, `cookies`, `headers`, `destroy`.

На этом этапе методы либо возвращают безопасные mock-значения, либо выбрасывают `NotImplementedError` для действий, которые могли бы имитировать реальное взаимодействие со страницей.

## BrowserManager

`BrowserManager` хранит конфигурацию, состояние запуска, health и метрики жизненного цикла. При `PLAYWRIGHT_ENABLED=false` реальный браузер не запускается; health сообщает, что инфраструктура готова, но Playwright пока не активирован.

## Как позже подключится Playwright

Позже можно добавить адаптер Playwright за `BrowserManager.start()` и реализацию методов `BrowserSession`. ENV `PLAYWRIGHT_ENABLED=true` станет feature flag для реального драйвера. Пул останется тем же: он будет выдавать сессии, оборачивающие browser context/page Playwright.

## Как позже подключится Selenium

Selenium можно подключить как альтернативный backend-драйвер тем же интерфейсом `BrowserSession`. Для этого достаточно добавить driver factory и выбрать реализацию через отдельный ENV, не меняя Provider Registry и бизнес-логику.

## Почему пока нет реальных сайтов

Текущий PR строит только промышленную архитектурную основу. Реальные сайты, селекторы, XPath, scraping и браузерная сеть намеренно исключены, чтобы не смешивать инфраструктурный слой с интеграциями конкретных провайдеров и не нарушать юридические или эксплуатационные границы.
