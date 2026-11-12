# DevSecOps CLI Kit для AWS Lambda

CLI для розгортання й експлуатації контейнерного застосунку AWS Lambda в явно
вибраному обліковому записі AWS. Один процес роботи: налаштування → збережений
план → перегляд → застосування → перевірка → відновлення або видалення.

Поточний випуск: **`1.0.1`** (GitHub prerelease). Попри номер patch-версії,
він змінює CLI несумісно з `1.0.0`; перед оновленням прочитайте
[посібник переходу](docs/upgrade-guide.md). AWS acceptance нового коду ще потрібне.

## Встановлення

Потрібні Git, Python 3.11–3.14, Terraform від 1.10.5 та AWS CLI v2.
Підтримувані цільові системи — macOS і Linux; Windows не перевірено.

```sh
git clone https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda.git
cd devsecops-pipeline-kit-aws-lambda
python3 -m venv .venv
.venv/bin/python -m pip install --no-deps .
.venv/bin/devsecops --version
.venv/bin/devsecops --help
```

Альтернатива — `sh install.sh --venv /absolute/path/to/new-venv`.
Інсталятор встановлює поточний checkout і відмовляється перезаписувати наявний каталог.
Збережіть checkout: wheel містить Python CLI, а Terraform залишається в репозиторії.
У командах нижче `devsecops` має бути доступний через PATH вашого virtualenv.

## Перше розгортання

Увійдіть в AWS через іменований профіль і незалежно перевірте account ID.
Усі значення облікового запису й URI нижче замініть своїми.

```sh
aws sts get-caller-identity --profile project
devsecops init service --expected-account-id 123456789012 --region eu-north-1 --profile project
devsecops plan service --stage registry
```

`init` зберігає локальні налаштування та перевіряє identity; ресурсів він не створює.
Прочитайте `plan.txt`, указаний у результаті планування. Потім застосуйте саме
цей план, підставивши його `plan_id` та SHA-256 **review.json**:

```sh
devsecops apply service --plan-id PLAN_ID --sha256 REVIEW_SHA256 --yes
```

Це створює KMS та ECR. Зберіть і опублікуйте власний Lambda-сумісний образ
у повернутий ECR-репозиторій своїм процесом збирання. CLI перевіряє готовий
образ, але не збирає його. Потрібні `linux/amd64`, підтримуваний Lambda runtime
і маршрут `GET /health`, що повертає HTTP 2xx.

```sh
devsecops plan service --stage workload --image-uri '123456789012.dkr.ecr.eu-north-1.amazonaws.com/YOUR_REPOSITORY@sha256:YOUR_DIGEST'
# Прочитайте новий plan.txt та використайте його власні ID і SHA-256:
devsecops apply service --plan-id WORKLOAD_PLAN_ID --sha256 WORKLOAD_REVIEW_SHA256 --yes
devsecops status service
devsecops request service --path /health
devsecops logs service
```

## Щоденна робота

```sh
devsecops config service --format json
devsecops concurrency service
devsecops request service --method POST --path /your-route --body '{"key":"value"}'
devsecops plan service --stage workload --image-uri 'YOUR_ECR_URI@sha256:NEW_DIGEST'
devsecops plan service --stage rollback --image-uri 'YOUR_ECR_URI@sha256:KNOWN_GOOD_DIGEST'
```

Кожне оновлення, ручне повернення образу та видалення проходять через новий
збережений план і його явне погодження. План чинний одну годину та використовується
для однієї спроби apply. Зміна source, settings, state або файлів плану робить його непридатним.
Автоматичне recovery після невдалого оновлення повертає попередній перевірений
образ; загальний результат розгортання залишається невдалим.

За низької квоти можна явно обрати спільний пул:
`devsecops concurrency service --mode unreserved`, після чого створити новий план.
Він не забезпечує окремої гарантованої ємності чи ліміту функції.

## Стан і межі підтримки

Стан, налаштування, плани й приватні докази лежать у
`.devsecops/deployments/<name>/`. Зберігайте їх резервну копію поза Git.
CLI працює з одним оператором і локальним backend; тег середовища залишається
`dev`. Він не є системою спільного керування production-розгортаннями.
API Gateway використовує IAM; HTTP-запити CLI підписуються SigV4.

Для переходу зі старого збереженого стану:
`devsecops migrate NAME`, перегляд результату, потім `devsecops migrate NAME --yes`.
Перехід локальний: імена й теги наявних AWS-ресурсів зберігаються; потрібен новий план.
Деталі — у [посібнику оновлення](docs/upgrade-guide.md).

Видалення виконуйте за [процедурою виведення з експлуатації](docs/runbooks/decommission.md):
резервування, зупинка записувачів, переглянуте очищення S3/ECR, destroy-план,
перевірка залишків і запланованого видалення ключів.

## Документація

- [Індекс](docs/README.md), [команди](docs/command-inventory.md), [контракти](docs/stability-contract.md).
- [Архітектура](docs/cli-architecture.md), [Mermaid-діаграми українською](docs/diagrams.uk.md).
- [Власний образ](docs/bring-your-own-image.md), [модель безпеки](docs/security-model.md), [AWS-дозволи](AWS_policy.md).
- [Діагностика](docs/troubleshooting.md), [вартість](docs/cost-estimation.md), [розробка й тести](CONTRIBUTING.md).
- [Підготовка релізу](docs/release-checklist.md): перевірки, артефакти й приймання нового коду в AWS.
