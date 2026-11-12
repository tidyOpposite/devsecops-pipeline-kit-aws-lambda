# Контракти поточної гілки

Версія `1.0.1` має статус GitHub prerelease та змінює CLI несумісно з `1.0.0`
попри номер patch-версії. Опублікований `1.0.0`
описує старий інтерфейс; його приклади не є командами цієї гілки.
Підтримувані команди наведено в [інвентарі](command-inventory.md).

## Налаштування та план

Deployment settings і основні результати мають `schema_version=2`.
Невідомі схеми, неправильні типи та чужа область відхиляються. Ідентичність
account/region/project/purpose зафіксована у settings, state та review.
Нове розгортання має `Purpose=Deployment`, `Environment=dev` і унікальний prefix.
Для явного переходу старого стану зберігається попередній ownership tag.

Review зв'язує settings, локальний state, код CLI, Terraform-модулі, provider lock,
image digest і чотири файли: plan.tfplan, plan.json, plan.txt, inputs.tfvars.json.
Оператор передає SHA-256 review.json. Строк дії — одна година. Маркер applied.json
записується перед apply: навіть невдалу спробу не можна повторно застосувати.
Потрібен новий переглянутий план. Під час apply план не перегенеровується.

## Виведення й коди завершення

`--format json` повертає один JSON-об'єкт без журналу зовнішніх команд у stdout.
Режим human додатково показує перебіг Terraform, після нього — результат.

| Код | Значення |
| --- | --- |
| 0 | Команду успішно виконано, або повернуто review-required без AWS-змін |
| 1 | Помилка перевірки, AWS, Terraform, health або recovery |
| 2 | Неправильні аргументи або відсутній зовнішній executable |
| 70 | Неочікувана внутрішня помилка без виведення traceback чи секретних значень |
| 130 | Переривання |

Основний envelope `kind=deployment` містить schema_version, status, name,
account_id, region, evidence та деталі операції. Відмова на межі CLI має
`kind=command-error`, command, error, exit_code. Перехід має
`kind=deployment-migration`, source, destination та status.
S3-маніфест має власну незмінену схему `1`; CLI обгортає результат cleanup
у deployment envelope. Докази state/HTTP є приватними локальними файлами.

Успішне recovery не перетворює невдале розгортання на успішне.
Config і concurrency не змінюють AWS; request може викликати бізнес-дії workload.
Порожній state після destroy потребує окремої перевірки фактичної відсутності ресурсів.
