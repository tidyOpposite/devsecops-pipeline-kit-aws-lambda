# Архітектура CLI

Один Python-пакет, один механізм розгортання та один Terraform root.
Архітектурні й поведінкові представлення наведено в [Mermaid-діаграмах](diagrams.uk.md).
Довгі алгоритми поділено на короткі горизонтальні частини з явними переходами.

| Модуль | Відповідальність |
| --- | --- |
| `__main__.py` | Вхід для `python -m devsecops_cli` |
| `main.py` | argparse, маршрутизація команд, формати результатів, коди виходу, scope cleanup |
| `deployment.py` | Налаштування, локальний lock, плани, apply, status, HTTP, logs і recovery |
| `aws.py` | Перевірка ECR-образу, account capacity, SigV4, заборона HTTP redirects |
| `images.py` | Розбір URI образів |
| `lambda_capacity.py` | Чисті правила перевірки ємності |
| `models.py` | Тип URI образу та доменна помилка валідації |
| `teardown.py` | Переглянуті S3-маніфести, пагінація, видалення версій і uploads |
| `migration.py` | Явний локальний перехід попереднього стану зі збереженням ownership |
| `paths.py` | Пошук checkout з урахуванням меж Git |
| `terraform/main.tf` | Прив'язаний до account ID локальний backend та композиція ресурсів |
| `terraform/modules/` | KMS, ECR, storage, Lambda, API Gateway та спільні імена бакетів |

Провайдерні команди проходять через `Deployment.aws` і `Deployment.tf`, які
можна підмінити в тестах. AWS CLI використовує іменований профіль; Terraform
отримує його credentials через `credential_process`. Випадкові `AWS_*` і `TF_*`
з оточення не визначають область розгортання.

`main.py` імпортує прикладні модулі; прикладні модулі не імпортують обробники CLI.
Перевірки ECR/SigV4 і capacity не залежать від термінального інтерфейсу.
Усі зміни AWS виконуються без GitHub-диспетчеризації.
