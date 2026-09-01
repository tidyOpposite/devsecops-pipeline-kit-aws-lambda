"""Dependency-free text formatting shared by CLI output modules."""


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


__all__ = ["markdown_table"]
