# Command Inventory

Use the inventory from the installed CLI for the complete list of commands,
stability labels, supported flags, JSON schemas and generated files:

```bash
devsecops inventory --format json
devsecops inventory --status stable --format markdown
devsecops lab plan --help
```

## Common Tasks

| Task | Command or guide |
| --- | --- |
| Open the interactive menu | `devsecops menu`. Press `i` for readiness details. |
| Start or resume the local demo | `devsecops setup --mode demo --yes --strict` |
| Show status and the next action | `devsecops status` or `devsecops` |
| Inspect and validate config | `devsecops config show`, `devsecops config validate`, `devsecops config diff` |
| Review generated changes | `devsecops generate --dry-run` |
| Inspect or restore local snapshots | `devsecops snapshot list`, `devsecops snapshot restore --last --dry-run` |
| Deploy or operate a dev Lambda | [Lab commands](single-operator-lab.md) |
| Operate a protected GitHub/OIDC workflow | [Experimental production walkthrough](experimental-production-walkthrough.md) |
| Verify release evidence | [Release checklist](release-checklist.md) |

## Script Contract

Use `--format json` where supported. Prefer the canonical command shown in
the inventory over a compatibility alias. See the
[stability contract](stability-contract.md) for versioning and output guarantees.

## Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Validation failed or the requested local selection was invalid. |
| `2` | Required external tool is missing, or command-line arguments are invalid. |
| `3` | External authentication is missing or invalid. |
| `70` | Unexpected runtime error. |
| `130` | Command was interrupted. |
