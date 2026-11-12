# Команди CLI

Використовуйте `devsecops COMMAND --help`. Кожна робоча команда приймає назву
розгортання та `--format human|json`. Без підкоманди CLI показує довідку з кодом 2.

| Команда | Призначення | Зміни |
| --- | --- | --- |
| `init NAME --expected-account-id ID --region REGION --profile PROFILE` | Зафіксувати область і перевірити AWS identity | Локальні settings; AWS лише читання |
| `plan NAME --stage registry` | Підготувати KMS/ECR до публікації образу | Локальний план; AWS читання |
| `plan NAME --stage workload --image-uri URI@sha256:DIGEST` | Спланувати перше розгортання чи оновлення | Локальний план; AWS читання |
| `plan NAME --stage rollback --image-uri URI@sha256:DIGEST` | Спланувати ручне повернення образу | Локальний план; AWS читання |
| `plan NAME --stage destroy` | Спланувати видалення записаних ресурсів | Локальний план; AWS читання |
| `apply NAME --plan-id ID --sha256 HASH` | Перевірити план і показати потребу погодження | AWS не змінюється |
| `apply NAME --plan-id ID --sha256 HASH --yes` | Застосувати саме збережений план | AWS створення/оновлення/видалення |
| `status NAME` | Звірити Lambda, state, /health і concurrency | AWS читання та підписаний GET |
| `request NAME --method GET --path /health` | Викликати власний API | Залежить від маршруту workload |
| `request NAME --method POST --path /route --body '{"key":"value"}'` | Надіслати JSON-об'єкт | Залежить від маршруту workload |
| `logs NAME` | Останні 50 подій за 15 хвилин із повною пагінацією | AWS читання |
| `config NAME` | Прочитати settings і перевірити область state | Локальні докази; без AWS |
| `concurrency NAME` | Показати локальну політику ємності | Локальне читання |
| `concurrency NAME --mode reserved --reserved-executions 10` | Обрати виділену ємність | Лише settings; потрібен новий план |
| `concurrency NAME --mode unreserved` | Явно обрати спільний пул | Лише settings; потрібен новий план |
| `cleanup NAME bucket-plan --bucket BUCKET --purpose workload-data --output FILE` | Зберегти інвентар версій і uploads | AWS читання |
| `cleanup NAME bucket-purge --bucket BUCKET --purpose workload-data --manifest FILE --sha256 HASH --acknowledge-backup` | Видалити лише погоджений інвентар | Незворотне видалення версій/завантажень |
| `migrate NAME` / `migrate NAME --yes` | Переглянути / виконати перехід старого каталогу | Локальний перехід без AWS |

Для бакета журналів використовуйте `--purpose workload-logs`. Bucket і purpose
мають відповідати ресурсам саме цього state. Backend і сторонні бакети через CLI не очищаються.
Відносні шляхи manifest/output обчислюються від кореня checkout.

POST обмежений JSON-об'єктом до 64 KiB. Шлях API має починатися з `/`,
містити ASCII-символи маршруту та не мати query, fragment або сегмента `..`.
API-відповідь обмежена 1 MiB; redirects не виконуються.
