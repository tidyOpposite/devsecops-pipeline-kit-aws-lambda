# Перехід до основного CLI

Версія `1.0.1` (GitHub prerelease) має новий інтерфейс і схему deployment settings `2`.
Попри номер patch-версії, команди несумісні з `1.0.0`.
Збережіть попередній CLI та резервні копії до зміни робочого середовища.
Під час оновлення репозиторію жодні AWS-операції не виконуються.

## Старий збережений стан одного оператора

Якщо існує `.devsecops/labs/NAME/settings.json`, не запускайте новий `init`
для того самого розгортання. Спочатку зупиніть старі CLI-операції, заархівуйте
весь каталог, перевірте account/region/project та виконайте:

```sh
devsecops migrate NAME --format json
# Перевірте source, destination та project_name:
devsecops migrate NAME --yes --format json
devsecops config NAME
devsecops status NAME
```

Команда локально переміщує каталог у `.devsecops/deployments/NAME/`, зберігає
settings.v1.json і переводить settings на схему 2. State та докази зберігаються;
імена ресурсів, account/region та попередній Purpose не змінюються.
На першому новому apply output `lab_context` буде замінено на `deployment_context`;
адреси managed resources залишаються тими самими. Перевірте повний новий план.

Перехід відмовляється перезаписувати destination, працювати з symlink, чужим
state або невідомою схемою. Після помилки переміщення оригінальні settings
відновлюються, резервна копія залишається для ручної перевірки. Не видаляйте
каталоги, щоб приховати помилку; встановіть, де лежить повний актуальний state.

Попередні плани недійсні: змінилися код, Terraform source, шляхи та схеми.
Створіть новий plan, прочитайте plan.txt і лише тоді застосовуйте його.
Старий CLI після переходу не повинен створювати другий стан для тих самих ресурсів.

## Що більше не підтримується

Demo/setup modes, lab namespace, GitHub/OIDC dispatch, production workflow,
Snyk/ZAP wrappers, навчальний Text Stats, presets, generated GitHub helpers,
старі меню й локальні snapshots прибрано з поточного продукту.
Окремий `cli/pyproject.toml` прибрано; встановлюйте та збирайте пакет із кореня.
Історія попередньої реалізації зберігається в Git.

Старі `.devsecops-pipeline.toml`, setup-state, snapshots та generated.auto.tfvars
не перезаписуються цим оновленням. Після резервування приберіть застарілі
`terraform/*.tfvars` / `*.auto.tfvars`: Terraform автоматично читає їх і може
показувати попередження про змінені змінні. Новий CLI передає повний власний
inputs.tfvars.json; TOML більше не є його джерелом налаштувань.

## Попередні GitHub/OIDC розгортання

Автоматичний перехід віддаленого S3/backend-state не реалізовано. Зупиніть dispatch
і всіх writers. Збережіть попередній checkout та незалежний state backup для
експлуатації або виведення таких ресурсів з експлуатації. Не запускайте `init`
для створення паралельного state і не застосовуйте новий локальний root поверх
remote state без окремої перевіреної міграції. Репозиторій не видаляє GitHub secrets,
OIDC trust, IAM-ролі чи наявні хмарні ресурси автоматично.
