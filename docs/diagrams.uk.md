# Діаграми основного CLI

## Зміст

1. [Загальний робочий цикл](#diagram-01)
2. [Початкове налаштування](#diagram-02)
3. [Створення збереженого плану](#diagram-03)
4. [Перевірка та застосування плану](#diagram-04)
5. [Відновлення після невдалого оновлення](#diagram-05)
6. [Підписаний HTTP-запит — UML-послідовність](#diagram-06)
7. [Придатність збереженого плану — UML-стани](#diagram-07)
8. [Залежності модулів — структурна UML-модель](#diagram-08)
9. [Ресурси AWS — структурна UML-модель](#diagram-09)
10. [Очищення власного S3-бакета](#diagram-10)
11. [Явний локальний перехід попереднього стану](#diagram-11)

<a id="diagram-01"></a>

## 1. Загальний робочий цикл

Кожен блок із командами позначає окремі виклики CLI оператором. `config` і
`concurrency` дозволяють перевірити локальні налаштування перед новим планом.
Готовий образ збирає та публікує зовнішній процес. Перехід до наступної операції
передбачає успіх попередньої; відмови деталізовано на наступних схемах.

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
flowchart LR
    S(["Нове розгортання"])
    INIT[["Налаштувати область<br/>init"]]
    REG[["Підготувати KMS/ECR<br/>plan registry → apply"]]
    IMAGE[/"Готовий образ у ECR<br/>Зовнішня публікація"/]
    DEPLOY[["Розгорнути образ<br/>plan workload → apply"]]
    OBSERVE[["Перевірити роботу<br/>status / request / logs"]]
    NEXT{"Наступна дія?"}
    ROLLBACK[["Повернути образ<br/>plan rollback → apply"]]
    REMOVE[["Очистити й видалити<br/>cleanup → plan destroy → apply"]]
    E(["Завершити сеанс"])
    S --> INIT --> REG --> IMAGE --> DEPLOY --> OBSERVE --> NEXT
    NEXT -->|Оновити| IMAGE
    NEXT -->|Відновити вручну| ROLLBACK --> OBSERVE
    NEXT -->|Видалити| REMOVE --> E
    NEXT -->|Залишити ресурси| E
```

<a id="diagram-02"></a>

## 2. Початкове налаштування

Джерела: `main.main`, `Deployment.initialize` і `execute`. Назва та checkout
перевіряються до операції. Підпроцес перевірки налаштувань відхиляє вже
ініціалізоване розгортання, перевіряє формат account/region/profile, наявність AWS CLI
та збіг STS account ID. Новий `init` не створює AWS-ресурсів.

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
flowchart LR
    S(["init NAME"])
    PROJECT[["Перевірити checkout<br/>та назву"]]
    LEGACY{"Є старий стан?"}
    MIGRATE[/"Відмова<br/>Потрібен migrate"/]
    STOP(["Кінець: відхилено"])
    LOCK["Заблокувати<br/>розгортання"]
    CHECK[["Перевірити налаштування<br/>та AWS identity"]]
    OK{"Перевірки<br/>успішні?"}
    ERROR[/"Повернути<br/>причину відмови"/]
    SAVE["Зберегти settings<br/>зі схемою 2"]
    DONE(["initialized"])
    S --> PROJECT --> LEGACY
    LEGACY -->|Так| MIGRATE --> STOP
    LEGACY -->|Ні| LOCK --> CHECK --> OK
    OK -->|Ні| ERROR --> STOP
    OK -->|Так| SAVE --> DONE
```

<a id="diagram-03"></a>

## 3. Створення збереженого плану

Джерела: `Deployment.plan`, `check_plan`, `source_digest`. Дві частини
належать одному виклику `plan`; локальний lock утримується до завершення.
Будь-яка відмова проміжної перевірки зупиняє планування й повертає помилку.

### 3а. Перевірка області та передумов

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
flowchart LR
    S(["plan NAME"])
    SCOPE[["Блокування й журнал<br/>Налаштування, STS, жива Lambda"]]
    STAGE{"Етап плану?"}
    IMAGE[["Перевірити capacity<br/>та новий digest у ECR"]]
    PREV{"Є попередня<br/>Lambda?"}
    ROLLBACK{"Це rollback?"}
    REJECT(["Відмова:<br/>немає функції"])
    HEALTH[["Перевірити її образ<br/>і підписаний /health"]]
    REG[["registry: workload<br/>ще не розгорнуто"]]
    DESTROY[["destroy: локальний<br/>state має існувати"]]
    E(["До частини 3б"])
    S --> SCOPE --> STAGE
    STAGE -->|workload / rollback| IMAGE --> PREV
    PREV -->|Так| HEALTH --> E
    PREV -->|Ні| ROLLBACK
    ROLLBACK -->|Так| REJECT
    ROLLBACK -->|Ні: workload| E
    STAGE -->|registry| REG --> E
    STAGE -->|destroy| DESTROY --> E
```

### 3б. Збереження та перевірка плану

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
flowchart LR
    S(["Із частини 3а"])
    INIT[["Ініціалізувати Terraform<br/>Локальний backend і lockfile"]]
    INPUTS["Створити plan-id<br/>та inputs.tfvars.json"]
    TF[["Зберегти plan.tfplan<br/>і його TXT/JSON"]]
    POLICY{"Дії й ownership<br/>дозволені?"}
    ERROR[/"Відхилити план<br/>Зберегти докази"/]
    REJECT(["Кінець: помилка"])
    REVIEW["Зберегти review.json<br/>Прив'язки, хеші, строк 1 год"]
    OUT[/"plan-id, SHA-256 review<br/>та шлях до plan.txt"/]
    E(["planned"])
    S --> INIT --> INPUTS --> TF --> POLICY
    POLICY -->|Ні| ERROR --> REJECT
    POLICY -->|Так| REVIEW --> OUT --> E
```

`rollback` без попередньої функції відхиляється. `registry` не може змінювати workload.
`check_plan` відхиляє імпорт, чужі теги/модулі та неявне видалення або заміну
в workload-плані. Для registry додаються targets KMS/ECR, для destroy — `-destroy`.

<a id="diagram-04"></a>

## 4. Перевірка та застосування плану

Джерела: `Deployment.reviewed` і `Deployment.apply`. Частина 4а завершується
**перед** спробою застосування; частина 4б виконує цю спробу. Прапорець `--yes`
дозволяє саме переглянутий збережений план. Його не перегенеровують під час apply.
Помилки до `applied.json` блокують apply. `DeploymentError` або переривання,
перехоплені всередині apply, спрямовуються до схеми 5.

### 4а. Перегляд, погодження та захист від повтору

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
flowchart LR
    S(["apply NAME"])
    I[/"plan-id, SHA-256 review<br/>прапорець --yes"/]
    REVIEW[["Перевірити чинність<br/>і прив'язки плану"]]
    YES{"Передано<br/>--yes?"}
    WAIT[/"Показати повний план<br/>review-required"/]
    STOP(["Кінець: без apply"])
    PRE[["Перевірити AWS і Lambda<br/>Образи та ємність за етапом"]]
    INIT[["Terraform init<br/>Повторно перевірити review"]]
    MARK["Записати applied.json<br/>Спробу використано"]
    E(["До частини 4б"])
    S --> I --> REVIEW --> YES
    YES -->|Ні| WAIT --> STOP
    YES -->|Так| PRE --> INIT --> MARK --> E
```

### 4б. Застосування та оцінка результату

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
flowchart LR
    S(["Із частини 4а"])
    APPLY[["terraform apply<br/>Збережений plan.tfplan"]]
    OK{"Apply успішний?"}
    STAGE{"Етап?"}
    REG[/"Адреса ECR<br/>registry-ready"/]
    REGEND(["Кінець: реєстр готовий"])
    EMPTY{"Керовані ресурси<br/>у стані відсутні?"}
    REMOVED(["destroyed"])
    VERIFY[["Звірити образ і стан<br/>Перевірити /health і ємність"]]
    HEALTH{"Усі перевірки<br/>успішні?"}
    DONE(["healthy"])
    APPLYFAIL[["Обробити відмову<br/>за схемою 5"]]
    APPLYEND(["failed"])
    DESTROYFAIL[["Обробити відмову<br/>за схемою 5"]]
    DESTROYEND(["failed"])
    HEALTHFAIL[["Обробити відмову<br/>за схемою 5"]]
    HEALTHEND(["failed"])
    S --> APPLY --> OK
    OK -->|Ні| APPLYFAIL --> APPLYEND
    OK -->|Так| STAGE
    STAGE -->|registry| REG --> REGEND
    STAGE -->|destroy| EMPTY
    EMPTY -->|Так| REMOVED
    EMPTY -->|Ні| DESTROYFAIL --> DESTROYEND
    STAGE -->|workload / rollback| VERIFY --> HEALTH
    HEALTH -->|Так| DONE
    HEALTH -->|Ні| HEALTHFAIL --> HEALTHEND
```

`reviewed` перевіряє ID, схему, строк дії, account/region, source/settings/state,
хеші чотирьох файлів плану та відсутність applied.json. Для workload/rollback
додатково перевіряються образи та capacity. Порожній state після destroy потребує
окремої перевірки відсутності ресурсів у AWS.

<a id="diagram-05"></a>

## 5. Відновлення після невдалого оновлення

Джерела: обробник відмови `Deployment.apply` та `Deployment.recover`.
Автоматичне recovery доступне для `workload`/`rollback` із попереднім образом,
перевіреним під час планування. Перше розгортання, `registry` й `destroy`
потребують ручного аналізу. Recovery повертає образ і узгоджує state;
решта часткових інфраструктурних змін потребує окремої перевірки.

### 5а. Вибір дії та загальний результат

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
flowchart LR
    S(["Відмова після<br/>спроби apply"])
    CAN{"Є допустима точка<br/>recovery для етапу?"}
    MANUAL[/"manual-attention<br/>Зберегти стан і докази"/]
    RUN[["Підготувати inputs<br/>Виконати частину 5б"]]
    OK{"Recovery<br/>успішне?"}
    RESTORED[/"recovery.status<br/>recovered"/]
    FAILED[/"recovery.status<br/>recovery-failed"/]
    E(["Загальний status: failed<br/>Ненульовий код виходу"])
    S --> CAN
    CAN -->|Ні| MANUAL --> E
    CAN -->|Так| RUN --> OK
    OK -->|Так| RESTORED --> E
    OK -->|Ні| FAILED --> E
```

### 5б. Відновлення й перевірка попереднього образу

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
flowchart LR
    S(["Виклик із 5а"])
    CHECK[["Звірити ARN<br/>та доступність digest"]]
    UPDATE[["Дочекатись оновлення<br/>Відновити код Lambda"]]
    LIVE[["Перечитати Lambda<br/>Звірити попередній образ"]]
    TF[["Зберегти й застосувати<br/>refresh-only план"]]
    VERIFY[["Звірити образ у стані<br/>Перевірити health і ємність"]]
    E(["Повернути успіх у 5а"])
    S --> CHECK --> UPDATE --> LIVE --> TF --> VERIFY --> E
```

Перехоплена помилка чи переривання будь-якого кроку частини 5б повертає
`recovery-failed` у 5а; підготовка inputs також належить до цієї спроби recovery.

<a id="diagram-06"></a>

## 6. Підписаний HTTP-запит — UML-послідовність

Джерела: `Deployment.request`, `health` та SigV4 у `aws.py`.
Час у UML-послідовності йде згори вниз. Локальні деталі згруповано, щоб зменшити
висоту. STS identity перевіряється на межі операції. Кожен запит перевіряє API,
єдиний `$default` маршрут із `AWS_IAM` та точну Lambda-інтеграцію.
HTTP-докази можуть містити дані застосунку; credentials не журналюються.

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","actorBkg":"#001E62","actorBorder":"#001E62","actorTextColor":"#FFFFFF","actorLineColor":"#001E62","signalColor":"#001E62","signalTextColor":"#001E62","labelBoxBkgColor":"#EEF2FA","labelBoxBorderColor":"#001E62","labelTextColor":"#001E62","loopTextColor":"#001E62","sequenceNumberColor":"#FFFFFF","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; } text.actor-man, text.actor-man tspan { fill: #001E62 !important; }"}}%%
sequenceDiagram
    autonumber
    actor O as Оператор
    participant C as CLI
    participant A as AWS CLI / API
    participant G as API Gateway
    participant L as Lambda
    O->>C: request NAME або перевірка health
    C->>A: Перевірити STS identity на межі операції
    A-->>C: Account ID
    C->>C: Звірити локальний state та endpoint
    C->>A: Прочитати API, маршрути та інтеграцію
    A-->>C: Ідентичність API, AWS_IAM, ARN Lambda
    alt Область або інтеграція не збігаються
        C-->>O: Відмова до підписаного запиту
    else Усі перевірки пройдено
        C->>A: Експортувати credentials профілю в пам'ять
        A-->>C: Тимчасові дані для підпису
        C->>G: HTTPS-запит із SigV4 без redirects
        opt IAM дозволяє виклик
            G->>L: Виклик AWS_PROXY
            L-->>G: Відповідь застосунку
        end
        G-->>C: HTTP-відповідь або відмова IAM
        C->>C: Зберегти приватні HTTP-докази
        C-->>O: Результат і код завершення
    end
```

Якщо IAM відмовляє, Lambda не викликається. `health()` повторює неуспішну
HTTP-відповідь до шести разів із паузою 2 с між спробами; мережевий виняток може
припинити перевірку раніше. Ліміти: JSON-об’єкт POST до 64 KiB, відповідь до 1 MiB.

<a id="diagram-07"></a>

## 7. Придатність збереженого плану — UML-стани

Це концептуальна модель перевірок `reviewed` і маркера `applied.json`,
а не окреме поле стану в програмі. У `review.json` зв'язано account, region,
образ, попередню Lambda та хеші source/settings/state/файлів плану.
Неправильний SHA-256, введений оператором, відхиляє виклик і не змінює сам план.

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","stateBkg":"#001E62","stateLabelColor":"#FFFFFF","transitionColor":"#001E62","transitionLabelColor":"#001E62","labelBackgroundColor":"#EEF2FA","specialStateColor":"#001E62","innerEndBackground":"#FFFFFF"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
stateDiagram-v2
    direction LR
    state "План відсутній" as Absent
    state "План чинний" as Valid
    state "План непридатний" as Invalid
    state "Спробу використано" as Attempted
    state "Спроба успішна" as Applied
    state "Спроба невдала" as Failed
    [*] --> Absent
    Absent --> Valid: plan зберіг файли й review
    Valid --> Valid: перегляд без --yes
    Valid --> Invalid: минула 1 год або змінилися прив'язки
    Valid --> Attempted: передумови пройдено, записано applied.json
    Attempted --> Applied: apply та перевірки успішні
    Attempted --> Failed: помилка або переривання
    Applied --> [*]
    Failed --> [*]
    Invalid --> [*]
```

<a id="diagram-08"></a>

## 8. Залежності модулів — структурна UML-модель

Класифікатори `module` позначають Python-модулі. Пунктирна стрілка
спрямована від залежного модуля до його залежності. Модель показує основні
реальні імпорти; підписи містять назви файлів для зіставлення з кодом.
Прикладні модулі не імпортують `main.py`.

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","classText":"#FFFFFF","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
classDiagram
    direction LR
    class Main["CLI: main.py"] {
        <<module>>
    }
    class Deployment["Розгортання: deployment.py"] {
        <<module>>
    }
    class AWS["AWS: aws.py"] {
        <<module>>
    }
    class Images["Образи: images.py"] {
        <<module>>
    }
    class Capacity["Ємність: lambda_capacity.py"] {
        <<module>>
    }
    class Models["Типи: models.py"] {
        <<module>>
    }
    class Cleanup["Очищення: teardown.py"] {
        <<module>>
    }
    class Migration["Перехід: migration.py"] {
        <<module>>
    }
    class Paths["Корінь проєкту: paths.py"] {
        <<module>>
    }
    Main ..> Deployment
    Main ..> Cleanup
    Main ..> Migration
    Main ..> Paths
    Migration ..> Deployment
    Deployment ..> AWS
    Deployment ..> Models
    AWS ..> Images
    AWS ..> Capacity
    AWS ..> Models
    Images ..> Models
    Capacity ..> Models
```

<a id="diagram-09"></a>

## 9. Ресурси AWS — структурна UML-модель

Класифікатори `service` позначають логічні ресурси. Це структурна модель,
а не порядок виконання Terraform. Суцільна стрілка — взаємодія, пунктирна —
залежність. Функція отримує право GetObject/PutObject у бакеті даних;
фактичний доступ залежить від workload. Додатковий бакет access logs використовує
SSE-S3. DLQ застосовується до невдалих асинхронних Lambda-викликів, а не до
синхронних HTTP-помилок.

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","classText":"#FFFFFF","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
classDiagram
    direction TB
    class API["API Gateway"] {
        <<service>>
    }
    class Lambda["Lambda: x86_64"] {
        <<service>>
    }
    class ECR["ECR: образ"] {
        <<service>>
    }
    class Data["S3: дані"] {
        <<service>>
    }
    class Logs["CloudWatch: журнали"] {
        <<service>>
    }
    class DLQ["SQS: DLQ"] {
        <<service>>
    }
    class KMS["KMS: ключ"] {
        <<service>>
    }
    class Role["IAM: роль Lambda"] {
        <<service>>
    }
    API --> Lambda : HTTP-виклик
    API --> Logs : доступ
    Lambda --> Logs : виконання
    Lambda ..> ECR : код
    Lambda ..> Role : дозволи
    Lambda ..> Data : читання / запис
    Lambda ..> DLQ : асинхронні відмови
    Data ..> KMS : SSE-KMS
    ECR ..> KMS : шифрування
    Logs ..> KMS : шифрування
    DLQ ..> KMS : шифрування
    Lambda ..> KMS : конфігурація
```

<a id="diagram-10"></a>

## 10. Очищення власного S3-бакета

Джерела: `main.cleanup`, `bucket_plan`, `bucket_purge` у `teardown.py`.
Маніфест має власну схему 1, строк дії одну годину та точні version/upload IDs.
Погодження видалення вимагає `--acknowledge-backup`; перевіряються SHA-256,
account/region/bucket, purpose, формат і повний актуальний інвентар.
Частини 10а і 10б виконуються в одному lock розгортання. Перед очищенням
оператор резервує потрібні дані та зупиняє записувачів.

### 10а. Область дії та вибір операції

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
flowchart LR
    S(["cleanup NAME"])
    LOAD[["Блокування, налаштування<br/>та приналежність ресурсів"]]
    OWN{"Бакет і його призначення<br/>відповідають стану?"}
    BAD(["Відмова до<br/>видалення"])
    AUTH[["Перевірити STS<br/>Використати profile"]]
    MODE{"Підкоманда?"}
    PLAN[["bucket-plan: повний<br/>інвентар і manifest"]]
    OUT[/"Маніфест та SHA-256<br/>для перегляду"/]
    E(["Кінець: без видалення"])
    PURGE[["bucket-purge<br/>Виконати частину 10б"]]
    DONE(["Повернути результат<br/>і приватні докази"])
    S --> LOAD --> OWN
    OWN -->|Ні| BAD
    OWN -->|Так| AUTH --> MODE
    MODE -->|bucket-plan| PLAN --> OUT --> E
    MODE -->|bucket-purge| PURGE --> DONE
```

### 10б. Перевірка погодження та точне видалення

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
flowchart LR
    S(["Виклик із 10а"])
    REVIEW[["Перевірити погодження<br/>Хеш, область, строк, призначення"]]
    INVENTORY[["Звірити власника й регіон<br/>Прочитати весь інвентар"]]
    SAME{"Інвентар дорівнює<br/>погодженому?"}
    STOP(["Відмова:<br/>потрібен новий план"])
    DELETE[["Видалити точні версії<br/>та перервати завантаження"]]
    EMPTY{"Після перевірки<br/>сховище порожнє?"}
    FAIL(["Незавершене очищення<br/>Зберегти стан і докази"])
    OK(["empty: дані очищено<br/>Повернути результат у 10а"])
    S --> REVIEW --> INVENTORY --> SAME
    SAME -->|Ні| STOP
    SAME -->|Так| DELETE --> EMPTY
    EMPTY -->|Ні| FAIL
    EMPTY -->|Так| OK
```

Відмова власника/регіону, неправильний manifest, помилка API чи часткове
видалення зупиняють операцію. Наявні версії та delete markers видаляються
пакетами до 1000 записів; uploads перериваються окремо. Cleanup не видаляє
бакет, ECR, KMS або Terraform state.

<a id="diagram-11"></a>

## 11. Явний локальний перехід попереднього стану

Джерело: `migration.migrate`. Ця сумісність зберігає керування вже наявними
ресурсами. Окремого старого режиму CLI немає. Обидві частини виконуються
локально, під одним lock старого каталогу, без звернень до AWS.

### 11а. Перевірка та перегляд переходу

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
flowchart LR
    S(["migrate NAME"])
    SOURCE[["Знайти старий каталог<br/>Відхилити символьні посилання<br/>Отримати блокування"]]
    VALID{"Цільовий каталог відсутній<br/>і старі дані коректні?"}
    BAD(["Відмовити<br/>Зберегти оригінали"])
    YES{"Передано<br/>--yes?"}
    OUT[/"review-required<br/>Source, destination, project"/]
    STOP(["Кінець: лише перегляд"])
    NEXT(["До частини 11б"])
    S --> SOURCE --> VALID
    VALID -->|Ні| BAD
    VALID -->|Так| YES
    YES -->|Ні| OUT --> STOP
    YES -->|Так| NEXT
```

### 11б. Збереження налаштувань і переміщення

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#001E62","primaryTextColor":"#FFFFFF","primaryBorderColor":"#001E62","lineColor":"#001E62","textColor":"#001E62","secondaryColor":"#EEF2FA","secondaryTextColor":"#001E62","secondaryBorderColor":"#001E62","tertiaryColor":"#EEF2FA","tertiaryTextColor":"#001E62","tertiaryBorderColor":"#001E62","edgeLabelBackground":"#EEF2FA","labelBackgroundColor":"#EEF2FA"},"themeCSS":".edgeLabel, .edgeLabel p, .edgeLabel span { color: #001E62 !important; fill: #001E62 !important; } .edgeLabel, .labelBkg { background-color: #EEF2FA !important; }"}}%%
flowchart LR
    S(["Із частини 11а"])
    BACKUP["Зберегти settings.v1.json<br/>Копію не перезаписувати"]
    UPDATE["Записати settings схеми 2<br/>Зберегти старе призначення"]
    MOVE["Перемістити каталог<br/>до deployments/NAME"]
    OK{"Переміщення<br/>успішне?"}
    RESTORE["Якщо джерело існує:<br/>відновити старі settings"]
    ERROR(["Помилка переходу<br/>Резервну копію збережено"])
    DONE(["migrated<br/>Створити новий план"])
    S --> BACKUP --> UPDATE --> MOVE --> OK
    OK -->|Ні: OSError| RESTORE --> ERROR
    OK -->|Так| DONE
```

State та імена ресурсів зберігаються. Старі плани після переходу непридатні.
Помилка запису backup до оновлення settings зупиняє перехід. OSError під час
оновлення settings або переміщення обробляється спробою відновлення старих
settings, якщо каталог джерела ще існує. Backup залишається для ручного аналізу.
