# v1.0.1

This release updates the documentation for the `v1.0.0` CLI and its
single-operator AWS dev lab. It includes the original `devsecops menu` and its
readiness view. The Python package version is `1.0.1`.

- Quick Start opens the interactive menu. Press `i` for readiness details.
- The documentation index points to installation, AWS deployment, rollback
  and cleanup. `devsecops inventory` provides the full command list.
- Experimental GitHub/OIDC production evidence has a separate verifier.

Install from the matching checkout:

```bash
git clone --branch v1.0.1 --depth 1 https://github.com/tidyOpposite/devsecops-pipeline-kit-aws-lambda.git devsecops-pipeline-kit &&
cd devsecops-pipeline-kit &&
sh install.sh --version v1.0.1 &&
export PATH="$HOME/.local/bin:$PATH" &&
devsecops menu
```

The AWS acceptance record covers `v1.0.0`. This documentation release used
manual publication without a new AWS acceptance run.
