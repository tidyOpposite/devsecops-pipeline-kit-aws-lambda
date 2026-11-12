# Модель безпеки

Довірені сторони: один оператор, локальний checkout, його state/settings і
іменований AWS profile. Захищайте локальну машину та резервні копії.

- STS account ID перевіряється перед хмарними операціями; provider додатково має allowed_account_ids.
- Terraform backend локальний, службові дані й lock ізольовані для кожного deployment.
- Зовнішні AWS/TF environment overrides не підміняють іменований профіль або inputs.
- Образ має бути digest URI у власному ECR: перевіряються manifest, config hash,
  linux/amd64, тип single-platform та можливість читати layer/config.
- Plan дозволяє лише визначені модулі, ownership tags і дії відповідного етапу.
  Імпорт та неявне видалення/заміна у workload-плані відхиляються.
- Review прив'язаний до source/settings/state/inputs і має строк дії та захист від повтору.
- Перед apply знову перевіряються identity, жива Lambda, образи, capacity і review.
- Health і request підписуються SigV4 лише після звірки live API, IAM route та інтеграції Lambda.
  Redirects відхиляються; credentials залишаються в пам'яті, secret-команди не журналюються.
- Recovery перевіряє попередній digest, ARN, state, health та concurrency.
- Cleanup працює лише з бакетами, записаними у state; маніфест погоджує точні
  version IDs і upload IDs. Повторно перевіряються account, owner, region та інвентар.

Залишкові межі: один оператор і локальний стан не забезпечують спільне погодження
чи distributed locking. Власник локального state може змінити також його докази;
хеші захищають від випадкового drift і підміни окремих файлів, а не від довіреного
оператора з повним доступом. HTTP/API авторизація бізнес-дій належить workload.
Вбудоване ECR scan_on_push не є блокувальним шлюзом apply за вразливостями.
CLI не надає Snyk/ZAP-гейтів або окремої production-процедури.

SQS DLQ застосовується до невдалих асинхронних Lambda-викликів. Синхронна
HTTP-помилка через API Gateway не потрапляє туди автоматично.
