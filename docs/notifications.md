# Notification Engine

Notification Engine добавляет внутренний центр уведомлений для изменений, найденных Monitoring Engine. На текущем этапе уведомления сохраняются только в приложении и не отправляются во внешние каналы.

## Архитектура

Пакет `backend/app/notifications` содержит:

- `Notification` — Pydantic-модель уведомления.
- `NotificationType` — тип события: `NEW_ROUTE`, `SEATS_AVAILABLE`, `BETTER_ROUTE`, `PRICE_CHANGED`, `MONITORING_FAILED`, `MONITORING_RESUMED`.
- `NotificationSeverity` — уровень важности: `info`, `success`, `warning`, `critical`.
- `NotificationRepository` — интерфейс хранилища.
- `FileNotificationRepository` — JSON repository, аналогичный SavedSearch repository.
- `NotificationService` — операции списка, непрочитанных, read/read-all/delete.
- `NotificationEngine` — преобразует результат Monitoring Engine в уведомление.

## Связь с Monitoring Engine

`MonitoringEngine.check()` получает предыдущее состояние из истории, выполняет проверку, сохраняет `MonitoringHistory`, затем передаёт `MonitoringResult` и предыдущую запись в `NotificationEngine`.

Правила:

- если изменений нет — уведомление не создаётся;
- если появились новые маршруты — создаётся `NEW_ROUTE`;
- если появились доступные места — создаётся `SEATS_AVAILABLE`;
- если улучшился лучший маршрут — создаётся `BETTER_ROUTE`;
- если мониторинг упал — создаётся `MONITORING_FAILED`;
- если после падения проверка снова успешна — создаётся `MONITORING_RESUMED`.

## API

- `GET /api/v1/notifications` — список уведомлений.
- `GET /api/v1/notifications/unread` — непрочитанные уведомления.
- `PATCH /api/v1/notifications/{id}/read` — отметить одно уведомление прочитанным.
- `PATCH /api/v1/notifications/read-all` — отметить все уведомления прочитанными.
- `DELETE /api/v1/notifications/{id}` — удалить уведомление.

## Frontend

В верхней панели добавлен внутренний Notification Center: кнопка с колокольчиком, badge с количеством непрочитанных и выпадающая панель с датой, типом, сообщением, цветом severity, кнопками «Прочитано» и «Удалить».

## Ограничения этапа

Не подключены Telegram, Email, Push, SMS и Webhook. Следующий этап — добавить настройки каналов доставки и адаптеры внешних провайдеров без изменения ядра Notification Engine.
