"""Dependency-free text formatting shared by CLI output modules."""

import re
import shutil
import unicodedata

_SGR = re.compile(r"\x1b\[[0-9;]*m")
_DISPLAY_TOKENS = re.compile(r"\x1b\[[0-9;]*m|.")


def terminal_width() -> int:
    return max(1, shutil.get_terminal_size((80, 24)).columns)


def display_width(text: str) -> int:
    """Count terminal cells, excluding ANSI color and combining characters."""

    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
               for char in _SGR.sub("", text))


def pad_text(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def _split_word(word: str, width: int, continuation_width: int) -> list[str]:
    parts, part, cells = [], "", 0
    for token in _DISPLAY_TOKENS.findall(word):
        size = 0 if _SGR.fullmatch(token) else display_width(token)
        if size and cells and cells + size > width:
            parts.append(part)
            part, cells = "", 0
            width = continuation_width
        part += token
        cells += size
    return [*parts, part] if part else parts


def wrap_text(text: str, width: int, subsequent_indent: str = "") -> list[str]:
    """Wrap human prose without dropping long paths, ANSI styles or Unicode."""

    width = max(1, width)
    lines = []
    for paragraph in text.splitlines() or [""]:
        prefix = re.match(r" *", paragraph).group()
        prefix = prefix[:max(0, width - 1)]
        continuation = (prefix + subsequent_indent)[:max(0, width - 1)]
        line = prefix
        for word in paragraph.split():
            if display_width(line) > display_width(prefix) and display_width(line + " " + word) > width:
                lines.append(line)
                line, prefix = continuation, continuation
            if display_width(line) > display_width(prefix):
                line += " "
            parts = _split_word(word, max(1, width - display_width(line)), max(1, width - display_width(continuation)))
            line += parts[0]
            if len(parts) > 1:
                lines.append(line)
                lines.extend(continuation + part for part in parts[1:-1])
                line, prefix = continuation + parts[-1], continuation
        lines.append(line.rstrip())
    return lines


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a compact GitHub-flavored Markdown table.

    Literal pipes inside cells are escaped so user or provider text cannot
    accidentally create additional columns.
    """

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines)


__all__ = ["display_width", "markdown_table", "pad_text", "terminal_width", "wrap_text"]
