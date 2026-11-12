# AWS-дозволи основного CLI

Оператор входить через іменований AWS CLI v2 profile. Не записуйте access keys
у repository, settings або плани. Перед init незалежно перевірте account ID.
Прив'язуйте операторську IAM-політику до account/region та унікального project prefix.
Це опис потрібних категорій доступу; остаточну політику перевіряйте за повним
Terraform-планом і політиками організації.

| Операція | Потрібний доступ |
| --- | --- |
| Identity | sts:GetCallerIdentity |
| ECR image validation | ecr:BatchGetImage, GetDownloadUrlForLayer, GetAuthorizationToken для власного реєстру |
| Concurrency | lambda:GetAccountSettings, GetFunctionConcurrency та читання функції |
| Plan/apply | Читання й керування ресурсами KMS, ECR, S3, Lambda, API Gateway, CloudWatch Logs, SQS та IAM у scope плану |
| Роль Lambda | iam:PassRole лише на створену execution role; без довільної передачі інших ролей |
| Recovery | lambda:GetFunction/GetFunctionConfiguration/UpdateFunctionCode та оновлення відомого Terraform state |
| HTTP | execute-api:Invoke лише для API цього deployment |
| Logs | logs:FilterLogEvents для його Lambda log group |
| S3 cleanup | Читання owner/location/versioning/versions/uploads; DeleteObjectVersion, AbortMultipartUpload лише для погоджених бакетів |

Terraform створює окрему execution role Lambda: запис у її logs, GetObject/PutObject
у workload data bucket, SendMessage у DLQ, tracing і використання workload KMS.
Це права функції; операторська роль керування має інше призначення.
API Gateway викликає Lambda через обмежений resource permission.

CLI не створює GitHub OIDC trust чи окремі plan/deploy ролі. Старі такі ресурси
не видаляються автоматично при оновленні; збережіть їх власника й окремий lifecycle plan.
Не обходьте Object Lock/MFA Delete/retention для виконання cleanup.
