# Business Trip Route Planner

Внутренний веб-сервис для поиска маршрутов командировок по России. Первый MVP не подключается к реальным транспортным API, не продаёт и не бронирует билеты, не содержит авторизации и работает на mock-данных.

## Текущий MVP

- Backend: Python + FastAPI.
- Frontend: Next.js + TypeScript + App Router.
- Поиск прямого маршрута и маршрута максимум с одной пересадкой.
- Проверка доступных мест на каждом сегменте для всей группы.
- Сортировка: меньше пересадок, затем меньше общее время в пути.
- Демо-режим во frontend, если backend не запущен.

## Структура каталогов

```text
backend/   FastAPI API, модели, провайдеры, маршрутный сервис и тесты
frontend/  Next.js приложение с русскоязычной страницей поиска
docs/      Архитектурная документация и границы MVP
```

## Как открыть проект

### Через GitHub/Codex без обязательной командной строки

1. Откройте репозиторий в GitHub или рабочей среде Codex.
2. Просмотрите `README.md`, `docs/architecture.md` и `docs/mvp-scope.md`.
3. Для проверки логики backend используйте встроенные тесты Codex или попросите Codex запустить тесты.
4. Для проверки frontend попросите Codex установить зависимости и запустить Next.js в режиме разработки.

### Windows

Команды ниже можно выполнить в PowerShell, но командная строка не обязательна, если вы работаете через GitHub/Codex.

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

После запуска frontend откройте `http://localhost:3000`. Backend по умолчанию ожидается на `http://localhost:8000`.

## API

### GET `/health`

Ответ:

```json
{ "status": "ok" }
```

### POST `/api/v1/routes/search`

Пример запроса:

```json
{
  "origin": "Москва",
  "destination": "Екатеринбург",
  "departure_date": "2026-08-10",
  "passengers": 2,
  "allowed_transport": ["train", "bus"],
  "max_transfers": 1,
  "minimum_transfer_minutes": 30
}
```

Пример ответа:

```json
{
  "routes": [
    {
      "id": "route-tr-msk-ekb-001",
      "origin": "Москва",
      "destination": "Екатеринбург",
      "segments": [
        {
          "id": "tr-msk-ekb-001",
          "origin": "Москва",
          "destination": "Екатеринбург",
          "transport_type": "train",
          "number": "Поезд 016М",
          "departure_time": "2026-08-10T09:00:00",
          "arrival_time": "2026-08-10T23:00:00",
          "available_seats": 8
        }
      ],
      "transfer_city": null,
      "transfer_duration_minutes": null,
      "total_duration_minutes": 840,
      "transfers_count": 0,
      "is_available_for_group": true
    }
  ]
}
```

## Что пока реализовано на mock-данных

- Города: Москва, Казань, Самара, Екатеринбург, Нижний Новгород.
- Поезда и автобусы как статический набор сегментов.
- Прямой маршрут Москва → Екатеринбург.
- Маршруты Москва → Казань → Екатеринбург и Москва → Самара → Екатеринбург.
- Сценарий Москва → Нижний Новгород → Екатеринбург, где на одном сегменте не хватает мест для группы.

## Следующие этапы

1. Добавить конфигурацию URL backend для разных окружений frontend.
2. Расширить календарную модель и поддержку ночных/многодневных рейсов.
3. Добавить реальные транспортные провайдеры через существующий интерфейс `TransportProvider`.
4. Добавить фильтры по времени отправления, типам перевозчиков и стоимости, когда появятся реальные данные.
5. Добавить хранение истории поисков только после согласования требований к данным и безопасности.

## Сохранённые заявки

MVP поддерживает «Заявки на командировку»: пользователь может сохранить параметры выполненного поиска, увидеть список заявок, открыть заявку, вручную запустить повторную проверку маршрутов и доступности мест, приостановить или возобновить флаг мониторинга и удалить заявку.

Backend добавляет endpoints `/api/v1/saved-searches`, а ручная проверка использует существующий Route Engine через текущий сервис поиска маршрутов. Реальные API РЖД, Telegram, PostgreSQL, Redis, авторизация и отдельные workers на этом этапе не подключаются.

Заявки временно хранятся в JSON-файле `data/saved-searches.json` или по пути из переменной окружения `SAVED_SEARCHES_FILE`. Файл добавлен в `.gitignore`, чтобы не хранить реальные пользовательские данные в репозитории. На Render локальная файловая система и `/tmp` могут очищаться после redeploy или перезапуска, поэтому сохранённые заявки могут исчезнуть. Это временное MVP-хранилище, которое позже следует заменить PostgreSQL.

Подробнее: [docs/saved-searches.md](docs/saved-searches.md).


### Яндекс Расписания

При `YANDEX_RASP_ENABLED=true` backend регистрирует provider `yandex_rasp` и обращается только к официальному API Яндекс Расписаний (`https://api.rasp.yandex.net/v3.0/search/` и `https://api.rasp.yandex.net/v3.0/stations_list/`). Ключ берётся из `YANDEX_RASP_API_KEY`, таймаут — из `YANDEX_RASP_TIMEOUT_SECONDS`. Если provider выключен, используются существующие Mock/GTFS/RZD provider без изменения их поведения.

Ограничение: API Яндекс Расписаний возвращает расписания и перевозчика, но не подтверждает наличие мест в текущей интеграции, поэтому UI показывает «Наличие мест пока не подтверждено». Для проверки мест нужен отдельный официальный источник availability/booking-данных перевозчиков.

#### Диагностика ответов Yandex Rasp

Backend сохраняет полную диагностику каждого HTTP-запроса к Yandex Rasp в `/tmp/business-trip-planner-diagnostics/`: `yandex_request.json`, `yandex_response.json`, `yandex_response.txt`, `yandex_headers.json` и `yandex_exception.txt`. При ошибках разбора или неожиданной структуре JSON поле `provider_errors.yandex_rasp.details` содержит URL, параметры запроса без значения `apikey`, HTTP-статус, headers, content-type, raw body, parsed JSON при успешном JSON-разборе, исключение, traceback и пути к этим artifact-файлам. Если body больше 1 MB, API-ответ содержит усечённый `raw_body`, а полный body остаётся в `yandex_response.txt`.
