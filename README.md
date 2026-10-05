# Kvitto Payments API

Тестовый сервис приёма платежей на Python 3.11+, FastAPI, Pydantic v2,
SQLAlchemy 2.x и SQLite. Деньги хранятся целыми копейками.

Реализованы тарифы, создание и чтение платежей, `Idempotency-Key`, рассрочка,
промокод, банковский вебхук, фильтрация платежей, Alembic, Docker Compose,
Ruff и GitHub Actions.

## Настройки

Настройки читаются из окружения или файла `.env`:

```env
DATABASE_URL=sqlite:///./kvitto.db
WEBHOOK_SECRET=
```

Если `WEBHOOK_SECRET` не задан или пуст, проверка подписи вебхука отключена для
простого локального запуска. При заданном секрете заголовок `X-Signature`
обязателен и содержит hex HMAC-SHA256 от точных сырых байтов тела запроса.

## Запуск с нуля в Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## Запуск с нуля в Linux или macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --reload
```

API работает на http://127.0.0.1:8000, Swagger — на
http://127.0.0.1:8000/docs. При старте приложение добавляет отсутствующие
тарифы; таблицы создаются только миграциями Alembic.

## Проверки

Windows:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -q
```

Linux/macOS:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m pytest -q
```

Тесты API используют отдельные временные базы и не меняют `kvitto.db`.

## Docker Compose

```powershell
docker compose up
```

Compose собирает Python 3.11 образ, выполняет `alembic upgrade head`, запускает
Uvicorn на `0.0.0.0:8000` и публикует порт на `localhost:8000`. SQLite хранится
в named volume `kvitto_data`. `WEBHOOK_SECRET` передаётся из окружения:

```powershell
$env:WEBHOOK_SECRET = "local-secret"
docker compose up
```

Если порт 8000 занят, хостовый порт можно изменить, например:

```powershell
$env:APP_PORT = "18080"
docker compose up
```

## Примеры API

Получить тарифы:

```powershell
curl.exe http://127.0.0.1:8000/tariffs
```

Создать рассрочку со скидкой и ключом идемпотентности:

```powershell
curl.exe -X POST http://127.0.0.1:8000/payments `
  -H 'Content-Type: application/json' `
  -H 'Idempotency-Key: enrollment-42' `
  -d '{"tariff_id":2,"email":"student@example.com","method":"installment","installment_months":3,"promo_code":"kvitto10"}'
```

Повтор этого запроса с тем же ключом возвращает исходный платёж и HTTP 200.

Получить платёж и список с фильтрами:

```powershell
curl.exe http://127.0.0.1:8000/payments/1
curl.exe 'http://127.0.0.1:8000/payments?email=student@example.com'
curl.exe 'http://127.0.0.1:8000/payments?status=pending'
curl.exe 'http://127.0.0.1:8000/payments?email=student@example.com&status=pending'
```

Список сортируется по `id`. Фильтры необязательны, неизвестный статус даёт 422,
а отсутствие совпадений — `[]`.

### Подписанный вебхук в PowerShell

Пример использует только стандартную библиотеку Python. Значение `$body`
передаётся в подпись и HTTP-запрос без пересериализации:

```powershell
$env:WEBHOOK_SECRET = "local-secret"
$body = '{"payment_id":1,"status":"succeeded"}'
$signature = .\.venv\Scripts\python.exe -c "import hashlib,hmac,os,sys; print(hmac.new(os.environ['WEBHOOK_SECRET'].encode(), sys.argv[1].encode(), hashlib.sha256).hexdigest())" $body

curl.exe -X POST http://127.0.0.1:8000/webhooks/bank `
  -H 'Content-Type: application/json' `
  -H "X-Signature: $signature" `
  --data-raw $body
```

Успех: `200 {"result":"ok"}`. Неизвестный платёж даёт 404. Неверная подпись
даёт 401. Запрещённый переход даёт точный ответ
`409 {"error":"invalid_transition"}`.

Разрешены только переходы `pending → succeeded`, `pending → failed` и
`succeeded → refunded`.

Вебхук выполняет условный запрос:

```sql
UPDATE payments
SET status = :new_status
WHERE id = :payment_id AND status = :previous_status
```

Если конкурентный запрос уже изменил статус, `rowcount` равен нулю: транзакция
откатывается и возвращается 409. Произвольные ошибки SQLite не маскируются.

## Переход существующей базы на Alembic

Рабочая `kvitto.db` была создана до подключения Alembic. Её схема фактически
сравнена с ORM metadata и начальной миграцией: различий не найдено. После этого
выполнен `alembic stamp head`, который добавил только номер ревизии и не запускал
DDL; хеш пользовательских строк до и после совпал.

Для другой существующей базы сначала сделайте резервную копию и сравните схему.
Если она полностью совпадает с начальной миграцией, отметьте её командой:

```powershell
.\.venv\Scripts\python.exe -m alembic stamp head
```

Не запускайте начальную миграцию поверх уже существующих таблиц без проверки.
Для новой базы всегда используйте `alembic upgrade head`.

## Принятые решения

- Для `card` и `sbp` ненулевой `installment_months` отклоняется с 422.
- Повтор валидного запроса с существующим `Idempotency-Key` возвращает исходный
  платёж до поиска нового тарифа и повторных расчётов.
- Пустой `WEBHOOK_SECRET` отключает HMAC для совместимости с обязательной частью.
- Пагинация `GET /payments` не добавлена: она не требуется заданием.
- SQLite возвращает дату без зоны, поэтому схема ответа явно помечает её UTC.

## Проверки и ограничения

- Полный набор тестов выполнен локально на Python 3.13 и в Docker-образе на Python 3.11.
- GitHub Actions успешно выполнил Ruff и pytest на Python 3.11 и 3.13.
- Проект не проверялся под нагрузкой нескольких экземпляров приложения.
