# v1.0.2-rc.1

This prerelease packages the documentation cleanup with the CLI from `v1.0.0`.
It includes the original `devsecops menu` and its readiness view. The Python
package version is `1.0.2rc1`. Stable AWS acceptance remains tied to `v1.0.0`.

- Quick Start opens the interactive menu. Press `i` for readiness details.
- The documentation index points to installation, the single-operator AWS lab,
  rollback and cleanup. `devsecops inventory` provides the full command list.
- Production evidence uses the separate experimental verifier. Older release
  notes remain available in the `v1.0.0` documentation snapshot.

To try this candidate, clone the matching tag and install it into a local venv:

```bash
git clone --branch v1.0.2-rc.1 --depth 1 https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda.git devsecops-rc &&
cd devsecops-rc &&
python3 -m venv .venv &&
.venv/bin/python -m pip install --no-deps . &&
.venv/bin/devsecops menu
```

The menu starts locally. Setup and AWS commands describe their actions before
you apply changes.
