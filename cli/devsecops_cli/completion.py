"""Shell completion metadata and deterministic script generators."""

from __future__ import annotations

import re
import textwrap


COMPLETION_SHELLS = ("bash", "zsh", "fish")
COMPLETION_COMMANDS = [
    "menu",
    "config",
    "next",
    "start",
    "criteria",
    "dry-run",
    "preflight",
    "health",
    "doctor",
    "aws",
    "render",
    "github",
    "terraform",
    "snapshot",
    "readiness",
    "report",
    "dashboard",
    "explain",
    "inventory",
    "evidence",
    "completion",
]
COMPLETION_SUBCOMMANDS = {
    "config": ["show", "new", "validate", "diff", "reset", "set", "create", "schema"],
    "doctor": ["local", "github", "aws", "branch", "actions", "all"],
    "aws": ["outputs", "doctor"],
    "github": ["setup", "doctor", "status", "branch"],
    "terraform": ["plan", "bootstrap"],
    "snapshot": ["list", "show", "restore"],
    "evidence": ["collect"],
    "preset": ["list", "show", "apply"],
    "completion": list(COMPLETION_SHELLS),
}
COMPLETION_OPTIONS = {
    "devsecops": ["--help", "--version"],
    "dashboard": ["--help", "--watch", "--interval", "--mode"],
    "config": ["--help", "--format"],
    "config show": ["--help", "--format"],
    "config new": ["--help", "--preset", "--force", "--render"],
    "config validate": ["--help", "--strict", "--format"],
    "config diff": ["--help", "--preset", "--exit-code"],
    "config reset": ["--help", "--preset", "--render"],
    "config set": ["--help", "--render"],
    "config create": ["--help", "--preset", "--force", "--render"],
    "config schema": ["--help", "--format"],
    "next": ["--help", "--format"],
    "start": ["--help", "--preset", "--render", "--yes"],
    "criteria": ["--help", "--format", "--evidence-dir", "--strict"],
    "doctor": ["--help", "--deep", "--strict", "--format"],
    "doctor local": ["--help", "--deep", "--strict", "--format"],
    "doctor github": ["--help", "--strict", "--format"],
    "doctor aws": ["--help", "--environment", "--strict", "--format"],
    "doctor branch": ["--help", "--branch", "--strict", "--format"],
    "doctor actions": ["--help", "--limit", "--strict", "--format"],
    "doctor all": ["--help", "--deep", "--branch", "--environment", "--strict", "--format"],
    "dry-run": ["--help", "--preset", "--image-uri", "--environment"],
    "preflight": ["--help", "--image-uri", "--environment", "--format"],
    "health": ["--help", "--url", "--timeout", "--aws-sigv4", "--aws-region", "--format"],
    "render": ["--help", "--dry-run"],
    "report": ["--help", "--deep", "--format", "--output", "--print"],
    "github": ["--help"],
    "github setup": ["--help", "--write", "--apply", "--deploy-role-arn", "--plan-role-arn", "--snyk-token"],
    "github doctor": ["--help", "--strict", "--format"],
    "github status": ["--help", "--limit", "--strict", "--format"],
    "github branch": ["--help", "--branch", "--strict", "--format"],
    "aws": ["--help"],
    "aws outputs": ["--help", "--environment", "--strict", "--format"],
    "aws doctor": ["--help", "--environment", "--strict", "--format"],
    "terraform": ["--help"],
    "terraform plan": ["--help", "--no-init", "--create-workspace"],
    "terraform bootstrap": ["--help", "--apply"],
    "snapshot": ["--help", "--format"],
    "snapshot list": ["--help", "--format"],
    "snapshot show": ["--help", "--format"],
    "snapshot restore": ["--help", "--to", "--last", "--dry-run", "--yes"],
    "readiness": ["--help", "--deep", "--strict", "--format"],
    "inventory": ["--help", "--format", "--status"],
    "evidence": ["--help"],
    "evidence collect": ["--help", "--rc", "--output"],
    "completion": ["--help", "--program"],
}

def shell_words(words: list[str] | tuple[str, ...]) -> str:
    return " ".join("'" + word.replace("'", "'\"'\"'") + "'" for word in words)


def indent_lines(lines: list[str], spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else "" for line in lines)


def completion_function_name(program: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", program)


def bash_completion_script(program: str) -> str:
    function_name = completion_function_name(program)
    command_cases = []
    for command, options in sorted(COMPLETION_OPTIONS.items()):
        if " " in command or command == "devsecops":
            continue
        command_cases.append(f"{command}) opts=\"{' '.join(options)}\" ;;")

    nested_cases = []
    for command, options in sorted(COMPLETION_OPTIONS.items()):
        if " " not in command:
            continue
        nested_cases.append(f"\"{command}\") opts=\"{' '.join(options)}\" ;;")

    subcommand_cases = []
    for command, subcommands in sorted(COMPLETION_SUBCOMMANDS.items()):
        subcommand_cases.append(
            textwrap.dedent(
                f"""\
                {command})
                  if [[ $COMP_CWORD -eq 2 ]]; then
                    COMPREPLY=( $(compgen -W "{' '.join(subcommands)}" -- "$cur") )
                    return
                  fi
                  ;;
                """
            ).rstrip()
        )

    return f"""# bash completion for {program}
_{function_name}_completion() {{
  local cur command subcommand opts
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  command="${{COMP_WORDS[1]}}"
  subcommand="${{COMP_WORDS[2]}}"

  if [[ "$cur" == -* ]]; then
    opts=""
    case "$command $subcommand" in
{indent_lines(nested_cases, 6)}
    esac
    if [[ -z "$opts" ]]; then
      case "$command" in
{indent_lines(command_cases, 8)}
        *) opts="{' '.join(COMPLETION_OPTIONS['devsecops'])}" ;;
      esac
    fi
    COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
    return
  fi

  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "{' '.join(COMPLETION_COMMANDS)}" -- "$cur") )
    return
  fi

  case "$command" in
{indent_lines(subcommand_cases, 4)}
  esac
}}

complete -F _{function_name}_completion {program}
"""


def zsh_completion_script(program: str) -> str:
    function_name = completion_function_name(program)
    command_cases = []
    for command, options in sorted(COMPLETION_OPTIONS.items()):
        if " " in command or command == "devsecops":
            continue
        command_cases.append(f"({command}) opts=({shell_words(options)}) ;;")

    nested_cases = []
    for command, options in sorted(COMPLETION_OPTIONS.items()):
        if " " not in command:
            continue
        nested_cases.append(f"(\"{command}\") opts=({shell_words(options)}) ;;")

    subcommand_cases = []
    for command, subcommands in sorted(COMPLETION_SUBCOMMANDS.items()):
        subcommand_cases.append(
            textwrap.dedent(
                f"""\
                {command})
                  if (( CURRENT == 3 )); then
                    compadd {shell_words(subcommands)}
                    return
                  fi
                  ;;
                """
            ).rstrip()
        )

    return f"""#compdef {program}

_{function_name}() {{
  local command subcommand
  command="$words[2]"
  subcommand="$words[3]"

  if (( CURRENT == 2 )); then
    compadd {shell_words(COMPLETION_COMMANDS)}
    return
  fi

  case "$command" in
{indent_lines(subcommand_cases, 4)}
  esac

  if [[ "$words[CURRENT]" == -* ]]; then
    local -a opts
    opts=()
    case "$command $subcommand" in
{indent_lines(nested_cases, 6)}
    esac
    if (( ${{#opts}} == 0 )); then
      case "$command" in
{indent_lines(command_cases, 8)}
        (*) opts=({shell_words(COMPLETION_OPTIONS['devsecops'])}) ;;
      esac
    fi
    compadd -a opts
  fi
}}

_{function_name} "$@"
"""


def fish_completion_script(program: str) -> str:
    all_options = sorted({option for options in COMPLETION_OPTIONS.values() for option in options if option.startswith("--")})
    lines = [
        f"# fish completion for {program}",
        f"complete -c {program} -f",
        f"complete -c {program} -n '__fish_use_subcommand' -a \"{' '.join(COMPLETION_COMMANDS)}\"",
    ]
    for command, subcommands in sorted(COMPLETION_SUBCOMMANDS.items()):
        condition = f"__fish_seen_subcommand_from {command}; and not __fish_seen_subcommand_from {' '.join(subcommands)}"
        lines.append(f"complete -c {program} -n '{condition}' -a \"{' '.join(subcommands)}\"")
    for option in all_options:
        lines.append(f"complete -c {program} -l {option[2:]}")
    return "\n".join(lines) + "\n"


def completion_script(shell: str, program: str = "devsecops") -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", program):
        raise ValueError("Completion program name must contain only letters, numbers, dots, dashes, or underscores.")
    if shell == "bash":
        return bash_completion_script(program)
    if shell == "zsh":
        return zsh_completion_script(program)
    if shell == "fish":
        return fish_completion_script(program)
    raise ValueError(f"Unsupported shell: {shell}")


__all__ = [
    "COMPLETION_COMMANDS",
    "COMPLETION_OPTIONS",
    "COMPLETION_SHELLS",
    "COMPLETION_SUBCOMMANDS",
    "bash_completion_script",
    "completion_function_name",
    "completion_script",
    "fish_completion_script",
    "indent_lines",
    "shell_words",
    "zsh_completion_script",
]
