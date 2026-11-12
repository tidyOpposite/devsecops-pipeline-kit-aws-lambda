# Діагностика

Почніть із `devsecops config NAME`, потім `devsecops status NAME` та `devsecops logs NAME`.
Deployment-операції зберігають приватні докази під каталогом розгортання.
Перегляньте result.json і command-*.json, якщо вони створені, не додаючи їх до Git.

| Симптом | Дія |
| --- | --- |
| Не знайдено checkout | Запускайте з checkout з terraform/main.tf, provider lock і модулями |
| Помилковий account або credentials | Перевірте іменований profile через AWS CLI; не редагуйте scope для обходу перевірки |
| План stale, changed або already attempted | Створіть новий plan, прочитайте його, використайте нові ID/SHA-256 |
| Образ відхилено | Звірте repository/account/region, digest, manifest і linux/amd64 |
| Бракує concurrency | Запитайте квоту або явно оберіть unreserved і перегляньте новий plan |
| Apply завершився частково | Збережіть state та докази; встановіть фактичний стан AWS перед новим планом |
| Health не повертає 2xx | Перевірте журнали, маршрут /health, runtime і IAM integration |
| recovery-failed | Звірте ARN, доступність попереднього digest та health; не вважайте функцію відновленою |
| Live Lambda не відповідає state | Дослідіть зовнішні зміни; не переписуйте state, щоб приховати drift |
| S3 inventory змінився | Зупиніть writers і access logging; створіть та погодьте новий маніфест |
| Cleanup має часткову помилку | Збережіть бакет/state/key, усуньте доступ/retention, повторно плануйте |

Apply не виконується без `--yes`. Відсутність змін у AWS після review-required —
очікувана поведінка. Recovery відновлює образ; інші часткові зміни інфраструктури
потребують аналізу. До повного завершення видалення див. [процедуру](runbooks/decommission.md).
