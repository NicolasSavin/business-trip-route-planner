# Деплой backend в Yandex Cloud Serverless Containers

Эта инструкция рассчитана на работу только через сайты GitHub, Codex и Yandex Cloud Console. Локальный терминал не нужен. GitHub Actions собирает образ backend, проверяет `/health` и публикует два тега в Yandex Container Registry: `latest` и полный SHA коммита.

## A. Подготовка в Yandex Cloud Console

1. Откройте [Yandex Cloud Console](https://console.yandex.cloud/), выберите нужные облако и каталог.
2. Откройте **Container Registry** и создайте реестр. Сохраните его идентификатор (**Registry ID**, обычно начинается с `crp`): нужен именно ID, а не имя реестра.
3. Откройте **Сервисные аккаунты** и создайте отдельный сервисный аккаунт для GitHub Actions.
4. Назначьте сервисному аккаунту роли на каталог или на созданный реестр:
   - `container-registry.images.pusher` — публикация образов из GitHub Actions;
   - `container-registry.images.puller` — скачивание образа Serverless Container.
5. В карточке сервисного аккаунта создайте **авторизованный ключ**, выберите формат JSON и скачайте файл. Откройте файл безопасным способом и скопируйте всё JSON-содержимое. Не добавляйте этот ключ в репозиторий, issue, логи или документацию.

## B. Добавление секретов в GitHub

1. На GitHub откройте репозиторий `NicolasSavin/business-trip-route-planner`.
2. Перейдите в **Settings → Secrets and variables → Actions**.
3. В разделе **Repository secrets** нажмите **New repository secret** и создайте:
   - `YC_SA_JSON_CREDENTIALS` — полное содержимое JSON авторизованного ключа;
   - `YC_REGISTRY_ID` — сохранённый идентификатор Container Registry.
4. Убедитесь, что в значениях нет добавленных кавычек. GitHub скрывает сохранённые значения секретов — это нормально.

Workflow проверяет наличие обоих секретов до сборки и завершится с понятным сообщением, если один из них пуст.

## C. Сборка и публикация через GitHub Actions

1. В репозитории откройте вкладку **Actions**.
2. Выберите workflow **Build Yandex Container image**.
3. Нажмите **Run workflow**, выберите ветку `main` и подтвердите запуск.
4. Дождитесь зелёного результата job `build-and-push`. В ходе job образ собирается, запускается с отключёнными RZD availability и Tutu Playwright, проверяется запросом `/health`, затем публикуется.

Workflow также запускается при изменениях `backend/**` или самого workflow в ветке `main`. Публикуются образы:

- `cr.yandex/<registry_id>/business-trip-route-planner-backend:latest`;
- `cr.yandex/<registry_id>/business-trip-route-planner-backend:<git_sha>`.

Для воспроизводимого отката можно выбрать тег с SHA конкретного успешного запуска вместо `latest`.

## D. Создание Serverless Container

1. В Yandex Cloud Console откройте **Serverless Containers** и создайте контейнер.
2. Создайте новую ревизию и укажите образ:
   `cr.yandex/<registry_id>/business-trip-route-planner-backend:latest`.
3. Если Console предлагает выбрать сервисный аккаунт для скачивания образа, выберите аккаунт с ролью `container-registry.images.puller`.
4. Задайте параметры ревизии:
   - порт: `8080`;
   - память: `512 MB` или `1 GB`;
   - timeout: `30 seconds`;
   - concurrency: значение по умолчанию;
   - публичный доступ: включить на время тестирования.
5. В разделе переменных окружения вручную добавьте значения из `backend/.env.yandex.example`. Для проверки RZD особенно важны `APP_ENV=development`, `RZD_AVAILABILITY_ENABLED=true` и `TUTU_ENABLED=false`. Не переносите комментарии и не добавляйте пустые секреты, если соответствующая интеграция не используется.
6. Создайте ревизию и дождитесь статуса готовности. Образ не содержит браузеры Chromium; обе Tutu-интеграции должны оставаться выключенными.

`APP_ENV=development` необходим для debug endpoint. После завершения диагностики ограничьте публичный доступ и переведите окружение в production с учётом того, что debug endpoints в production недоступны.

## E. Проверка после деплоя

Скопируйте публичный URL контейнера из Console и откройте в браузере:

1. `<URL>/health` — ожидается HTTP 200 и `{"status":"ok"}`.
2. `<URL>/docs` — должна открыться Swagger UI.
3. В Swagger UI раскройте `POST /api/v1/debug/rzd/http-probe`, нажмите **Try it out**, затем **Execute**. Сравните результаты `base_probe`, `pricing_probe` и этапа `ticket_search` с результатом на Render.

Если проверка не проходит, откройте логи активной ревизии в Yandex Cloud Console. Проверьте, что используется свежая ревизия с нужным образом, порт равен `8080`, `APP_ENV` оставлен равным `development`, а Tutu отключён.
