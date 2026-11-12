# Виведення з експлуатації

Це процедура оператора, а не автоматичне видалення всього за одну команду.
Нижче NAME, BUCKET, PROFILE та інші placeholders замініть перевіреними значеннями.

1. Незалежно звірте account/region/resource IDs. Заархівуйте весь deployment,
   state, settings, образи й потрібні дані; перевірте можливість відновлення.
2. Якщо дані або ключ потрібні надалі, оберіть збереження, зафіксуйте власника
   й вартість; не застосовуйте повний destroy-план.
3. Для видалення зупиніть клієнтів, writers та одночасні CLI/Terraform-операції.
   Дочекайтеся активних викликів. Вимкніть S3 access logging бакета даних
   перед очищенням бакета журналів, наприклад через AWS CLI з тим самим profile,
   region та expected-bucket-owner. Зупиніть зовнішню публікацію образів.
4. Експортуйте потрібні CloudWatch logs та DLQ messages. Перевірте, що копії
   даних читаються незалежно від KMS-ключа, який буде видалено.
5. Створіть окремий маніфест для кожного versioned бакета зі state:

```sh
devsecops cleanup NAME bucket-plan --bucket BUCKET --purpose workload-data --output data-inventory.json
# Прочитайте весь manifest та зафіксуйте його SHA-256:
devsecops cleanup NAME bucket-purge --bucket BUCKET --purpose workload-data --manifest data-inventory.json --sha256 MANIFEST_SHA256 --acknowledge-backup
```

Для журналів використовуйте workload-logs та окремий manifest. CLI перевіряє
scope state, live owner, region, строк дії й повний актуальний інвентар. Видаляються
точні version IDs, delete markers та погоджені multipart uploads. Зміна інвентарю,
retention refusal або часткова помилка означає незавершений результат і новий план.
Бакет, ECR і ключі команда cleanup не видаляє.

6. У власному ECR-репозиторії прочитайте повний `list-images` через правильний
   profile/region/registry-id; збережіть потрібні digest поза retiring stack.
   Видаліть погоджені образи через `batch-delete-image`, перевіряючи failures
   кожного виклику, та повторно переконайтеся в порожньому imageIds. Не використовуйте force.
7. Створіть і прочитайте destroy-план, а потім застосуйте його точні ID/SHA-256:

```sh
devsecops plan NAME --stage destroy
devsecops apply NAME --plan-id DESTROY_PLAN_ID --sha256 DESTROY_REVIEW_SHA256 --yes
```

8. Перевірте порожній state та відсутність конкретних ресурсів через AWS API.
   Access denied, timeout або неправильний регіон не доводять відсутності.
9. Для KMS зафіксуйте PendingDeletion та дату; повторіть перевірку після
   вікна видалення. Пізніше перевірте Billing і незалежні backups/exports.
10. Збережіть фінальний state й докази. Для retained або неперевірених ресурсів
    запишіть власника, причину й наступну дію. Не позначайте їх повністю видаленими.

Локальний backend не потребує видалення S3 state-бакета. Зовнішні старі backend,
ролі, OIDC trust або інші ресурси попередніх інтеграцій потребують окремого
обліку й перевіреного плану у відповідному старому checkout.
