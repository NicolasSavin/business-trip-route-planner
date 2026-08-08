# Protected hotels directory

The hotels catalogue is available at `/hotels`. Authentication is performed only
by the backend using `HOTELS_USERS_JSON`; the browser receives an HttpOnly signed
session cookie and never receives the configured credential list. Set a long,
random `HOTELS_SESSION_SECRET` in every deployed environment.

## Credentials

`HOTELS_USERS_JSON` is a JSON array of `surname` and `password` objects. Keep the
real value in the deployment secret store. Do not commit it. `HOTELS_ADMIN_SURNAME`
selects the administrator by case-insensitive surname. The source employee list
must omit Фурин Андрей Николаевич; the backend additionally rejects the known
excluded Мельников/2403 record if it is configured accidentally.

## Persistence

The API uses the `HotelRepository` interface and currently provides an
atomic, file-backed JSON implementation. The committed `seed.json` is copied only
when the configured data file does not exist. Set `HOTELS_DATA_PATH` to a path on
a durable mounted volume. Docker Compose does this with the `hotels-data` volume.

The default `/tmp/business-trip-hotels.json` path is **ephemeral**. Render's
current free service does not provide a durable filesystem, so administrator
changes there will be lost on restart or redeploy. Attach a persistent disk (and
change `HOTELS_DATA_PATH` to its mount path), or implement another
`HotelRepository` backed by the deployment database, before treating mutations
as durable.
