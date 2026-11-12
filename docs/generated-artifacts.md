# Локальні артефакти

Джерело налаштувань одного розгортання —
`.devsecops/deployments/<name>/settings.json`. Воно містить account, region,
іменований AWS profile, унікальний project_name, purpose і політику concurrency.
Credentials і токени в settings не записуються.

| Шлях від каталогу розгортання | Призначення |
| --- | --- |
| `settings.json` | Налаштування зі схемою 2 |
| `state.tfstate` | Локальний Terraform state; зберігайте резервну копію |
| `.lock` | Заборона одночасних CLI-операцій |
| `terraform-data/` | Ізольована службова область Terraform |
| `credentials.py`, `aws-runtime-config`, `aws-empty-credentials` | Міст credential_process без збережених значень credentials |
| `plans/<id>/inputs.tfvars.json` | Точні inputs збереженого плану |
| `plans/<id>/plan.tfplan`, `plan.json`, `plan.txt` | Binary та представлення для перевірки |
| `plans/<id>/review.json` | Прив'язки, строк дії й хеші |
| `plans/<id>/applied.json` | План уже використано для спроби |
| `evidence/<event>/` | Metadata операції, команди, HTTP-відповіді, result.json, SHA256SUMS.json |
| `settings.v1.json` | Резервна копія налаштувань при явному переході |

Каталог розгортання має приватні права; state, плани й докази можуть містити
внутрішні ідентифікатори, дані workload та чутливі атрибути провайдера. Не додавайте
їх до Git. Перед оновленням або видаленням резервуйте весь каталог.
Резервна копія state не відновлює видалені S3-версії або відсутній ECR-образ.

GitHub helpers, readiness-звіти, setup-state та TOML-пресети більше не генеруються.
Після переходу старі локальні файли можна заархівувати за [посібником](upgrade-guide.md).
