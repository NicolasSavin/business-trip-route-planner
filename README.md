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
