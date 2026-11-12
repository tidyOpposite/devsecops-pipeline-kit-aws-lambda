# Розробка й перевірки

Основний продукт — один CLI і один Terraform root. Нову поведінку додавайте
до deployment/provider modules, а argparse і форматування — до main.py.
Доменні модулі не імпортують main. Не додавайте альтернативні demo/cloud runners.

```sh
python3 -m pip install ruff==0.17.4 build==1.5.0 twine==7.0.0
ruff check cli/devsecops_cli cli/tests
ruff format --check cli/devsecops_cli cli/tests
PYTHONPATH=cli python3 -m unittest discover -s cli/tests
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform init -backend=false -input=false -lockfile=readonly
terraform -chdir=terraform validate -no-color
terraform -chdir=terraform test -no-color
python3 -m build
python3 -m twine check dist/*.whl dist/devsecops_pipeline_cli-*.tar.gz
```

Під час оновлення провайдера фіксуйте перевірені пакети для всіх цільових
платформ, а не лише поточної машини. Після `terraform init` виконайте:

```sh
terraform -chdir=terraform providers lock \
  -platform=linux_amd64 -platform=linux_arm64 \
  -platform=darwin_amd64 -platform=darwin_arm64
```

Коміт містить оновлений `.terraform.lock.hcl`; CI та CLI продовжують використовувати
`-lockfile=readonly`. Перевірка пакетів провайдера залишається обов'язковою.

Python-тести підміняють AWS/Terraform та перевіряють неправильний account,
immutable plans, replay, drift, recovery, SigV4, credential isolation,
міграцію й scoped cleanup. Terraform тести використовують mock_provider aws.
Вони не створюють AWS-ресурсів. За відсутності AWS CLI offline pagination
integration пропускається; задайте DEVSECOPS_TEST_AWS_CLI шляхом до aws.

Для real-provider credential-process integration проти локального STS задайте
DEVSECOPS_TEST_TERRAFORM та DEVSECOPS_TEST_AWS_PROVIDER_DIR і запустіть
`test_credentials.py`. Справжні AWS credentials не потрібні.
CI перевіряє Python 3.11–3.14 на Linux/macOS, пакет і mocked Terraform root.
CI також зберігає файли кандидата; їхній склад і правила публікації описані
в [процедурі релізу](docs/release-checklist.md).
Перевірки справжнього AWS deployment запускає оператор окремо, з явним
account/profile та переглянутим plan/apply. Локальні mocks не є доказом cloud acceptance.

Після зміни команд оновіть README, inventory, contracts, upgrade notes і Mermaid-діаграми.
