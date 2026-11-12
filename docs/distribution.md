# Встановлення й перевірка пакета

Python 3.11–3.14, AWS CLI v2 та Terraform від 1.10.5. Runtime CLI не має сторонніх
Python-залежностей. Використовуйте virtualenv на macOS або Linux.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-deps .
.venv/bin/devsecops --version
.venv/bin/devsecops --help
```

`sh install.sh --venv NEW_DIRECTORY --python /path/to/python3` виконує встановлення
цього checkout. Наявне призначення не перезаписується. Для оновлення створіть
новий virtualenv, перевірте його і лише потім перемикайте PATH.
Інсталятор не завантажує попередню опубліковану версію з іншим CLI.

Єдине джерело метаданих пакета — кореневий `pyproject.toml`.
Збирайте пакет командою `python3 -m build` з кореня репозиторію.
Wheel і Python sdist містять Python-пакет. Terraform, його lock і модулі беруться з checkout;
запускайте команди з нього або його підкаталогів. Зафіксуйте `git rev-parse HEAD`
та `devsecops --version` для відтворюваної перевірки.

CI зберігає wheel, sdist, повний архів вихідного коду, `SOURCE_COMMIT` та
`SHA256SUMS` як `core-release-candidate`. Для роботи без Git використовуйте повний
архів `devsecops-cli-kit-VERSION-source.tar.gz`: він містить Terraform, lock,
модулі та `install.sh`. Самостійний wheel або Python sdist не замінює цей каталог.
CI лише готує файли; публікацію регулює [процедура релізу](release-checklist.md).

`1.0.1` має статус GitHub prerelease; AWS acceptance нового CLI ще потрібне.
Попри patch-номер, він несумісний із CLI `1.0.0`; дотримуйтеся [посібника переходу](upgrade-guide.md).
Сумісність Windows і спільний багатокористувацький backend не заявляються.
