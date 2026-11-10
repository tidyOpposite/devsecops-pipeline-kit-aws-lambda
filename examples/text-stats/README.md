# Text Stats: Lambda для дипломної демонстрації

Невеликий API аналізує текст українською або іншою мовою. Він не зберігає
текст, не записує його в логи, не звертається до зовнішніх сервісів і не
потребує бази даних чи сторонніх Python-бібліотек. Захист доступу забезпечує
API Gateway з `AWS_IAM`, як у типовій конфігурації kit.

| Запит | Результат |
| --- | --- |
| `GET /` | Назва сервісу, release і доступні маршрути. |
| `GET /health` | HTTP 200 для справної версії, HTTP 503 у спеціальному образі перевірки відкату. |
| `GET /version` | Release та версія контракту API. |
| `POST /analyze` | Статистика тексту з JSON `{"text":"Привіт, дипломний проєкт!"}`. |

Для прикладу вище: **3 слова, 25 символів, 1 рядок, 46 байтів UTF-8**.
Відповідь також містить SHA-256 точних UTF-8 байтів і release образу.
«Слова» — непорожні частини, розділені Unicode-пробільними символами;
«символи» — Unicode code points, включно з пробілами; це не кількість
видимих графем. Рядки визначаються `str.splitlines()`; кінцевий перенос
не додає порожнього рядка. Ліміт тексту — 10 000 code points, тіла —
65 536 байтів після декодування base64. Невалідні дані дають 400, завеликий
запит — 413, неправильний Content-Type — 415, метод — 405, маршрут — 404.

## Локальна перевірка без AWS

Команди виконуються з кореня репозиторію на Python 3.11–3.14:

```bash
python3 -m unittest discover -s examples/text-stats/tests -v
python3 examples/text-stats/invoke.py examples/text-stats/events/health.json
python3 examples/text-stats/invoke.py examples/text-stats/events/analyze.json
```

`invoke.py` викликає справжній обробник із подією API Gateway HTTP API v2;
це локальна перевірка Python, а не доказ деплою в AWS.
CI запускає тести прикладу на кожній підтримуваній версії Python.

## Три незмінні образи

Dockerfile використовує офіційний Python 3.13 Lambda base image, зафіксований
digest саме для `linux/amd64` (перевірено 6 листопада 2026).
Перед фінальним прийманням перевірити оновлення й результати сканування
базового образу. `--provenance=false` запобігає створенню index замість
сумісного з Lambda маніфесту. Див. [інструкцію AWS](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html).

```bash
docker buildx build --platform linux/amd64 --provenance=false --load \
  --build-arg APP_RELEASE=demo-a --build-arg APP_HEALTH=healthy \
  -t devsecops-text-stats:demo-a examples/text-stats
docker buildx build --platform linux/amd64 --provenance=false --load \
  --build-arg APP_RELEASE=demo-b --build-arg APP_HEALTH=healthy \
  -t devsecops-text-stats:demo-b examples/text-stats
docker buildx build --platform linux/amd64 --provenance=false --load \
  --build-arg APP_RELEASE=demo-fail --build-arg APP_HEALTH=failing \
  -t devsecops-text-stats:demo-fail examples/text-stats
```

`demo-a` і `demo-b` відрізняються release у вмісті образу, тому матимуть різні
digests. `demo-fail` навмисно провалює `/health`; використовувати його лише
для запланованої перевірки відкату після вже успішного першого розгортання.
Це окремий тестовий образ; перемикача поломки через HTTP немає.

Перевірка контейнера через AWS Runtime Interface Emulator:

```bash
docker run --rm -d --name devsecops-text-stats-local --platform linux/amd64 \
  -p 127.0.0.1:9000:8080 devsecops-text-stats:demo-a
curl --fail-with-body --silent --show-error \
  -H 'Content-Type: application/json' \
  --data-binary @examples/text-stats/events/health.json \
  http://127.0.0.1:9000/2015-03-31/functions/function/invocations
curl --fail-with-body --silent --show-error \
  -H 'Content-Type: application/json' \
  --data-binary @examples/text-stats/events/analyze.json \
  http://127.0.0.1:9000/2015-03-31/functions/function/invocations
docker stop devsecops-text-stats-local
```

Перевіряти **внутрішнє `statusCode` і JSON `body`**: HTTP 200 від емулятора
підтверджує виклик Lambda, а статус відповіді API лежить усередині.
Порт доступний тільки на localhost. Повторити для `demo-b` і `demo-fail`;
у останнього `/health` має повернути внутрішній 503.

## Публікація й розгортання — пізніше

Зараз виконуються тільки локальні перевірки. Після завершення виправлень
образи потрібно опублікувати у ECR того самого регіону, записати три digests
і пройти [контракт образу](../../docs/bring-your-own-image.md). Використовувати
унікальні теги з Git SHA та release, а для деплою — URI за digest.
Ці локальні теги не слід перезаписувати в ECR.

Приклад не змінює `prod` approval policy і не додає шлях обходу reviewer.
Одноосібний хмарний сценарій ще потребує окремої реалізації та перевірки;
production і multi-account приймання залишаються відкритими.
Зберігати фактичні результати, скріншоти й власний звіт локально, наприклад
у `dist/devsecops/diploma-evidence/` або `docs/local/`; ці матеріали не
публікуються разом із кодом.
