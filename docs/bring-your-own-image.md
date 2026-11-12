# Власний Lambda-образ

Збирання, тести залежностей і публікація образу належать процесу вашого workload.
Спочатку застосуйте registry-план, потім опублікуйте образ у повернутий ECR.
CLI приймає digest URI з того самого account/region/repository.

Потрібні single-platform Linux amd64 (`x86_64` у Lambda), Docker V2 або OCI
manifest і Lambda Runtime Interface Client / сумісний runtime. Multi-platform
index відхиляється. Залежно від build-інструмента вимкніть створення provenance
index, щоб опублікувати один підтримуваний manifest.

API Gateway передає payload v2.0; застосунок повертає statusCode, headers і body.
Реалізуйте `GET /health` із HTTP 2xx для справного образу: перевірка є обов'язковою.
Власні GET/POST маршрути викликайте через `devsecops request NAME`.
Текстовий аналізатор або інший демонстраційний workload не входить у продукт.

Збережіть попередній перевірений ECR digest: без нього автоматичне recovery
невдалого першого розгортання неможливе. Не очищайте образи, потрібні для rollback.
