"""Add the Forum app to a server settings file without executing or replacing it."""
import ast
import sys
from pathlib import Path


def enable_forum(source):
    tree = ast.parse(source)
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id == "INSTALLED_APPS"]
    stores = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
              and node.id == "INSTALLED_APPS" and isinstance(node.ctx, ast.Store)]
    if len(assignments) != 1 or len(stores) != 1:
        raise ValueError("INSTALLED_APPS ist nicht eindeutig definiert.")
    value = assignments[0].value
    if not isinstance(value, (ast.List, ast.Tuple)):
        raise ValueError("INSTALLED_APPS ist keine direkte Liste oder ein Tupel.")
    apps = ast.literal_eval(value)
    if not all(isinstance(app, str) for app in apps):
        raise ValueError("INSTALLED_APPS enthaelt unbekannte Eintraege.")
    if any(app == "forum" or app.startswith("forum.") for app in apps):
        return source
    # AST columns are UTF-8 byte offsets. Inserting just after the opening
    # bracket preserves every existing setting, app entry, and comment.
    data = source.encode("utf-8")
    lines = data.splitlines(keepends=True)
    offset = sum(map(len, lines[:value.lineno - 1])) + value.col_offset + 1
    insertion = b'\n    "forum",' if value.end_lineno > value.lineno else b'"forum", '
    result = (data[:offset] + insertion + data[offset:]).decode("utf-8")
    ast.parse(result)
    return result


if __name__ == "__main__":
    try:
        source = Path(sys.argv[1]).read_text(encoding="utf-8")
        result = enable_forum(source)
        Path(sys.argv[2]).write_text(result, encoding="utf-8")
    except (SyntaxError, ValueError, OSError):
        # Never include source lines: server settings can contain secrets.
        raise SystemExit("Forum-App konnte nicht eindeutig in INSTALLED_APPS ergaenzt werden. Nichts installiert.")
