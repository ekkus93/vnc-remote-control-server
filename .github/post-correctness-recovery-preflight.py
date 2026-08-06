from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    ROOT / ".github/post-correctness-recovery.py",
    ROOT / ".github/post-correctness-recovery-boundary-fix.py",
)
texts: dict[str, str] = {}


def literal(node: ast.AST) -> str:
    value = ast.literal_eval(node)
    if not isinstance(value, str):
        raise SystemExit(f"non-string exact-anchor argument at line {getattr(node, 'lineno', '?')}")
    return value


for script in SCRIPTS:
    tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not isinstance(call.func, ast.Name):
            continue
        name = call.func.id
        if name not in {"replace_once", "insert_before_once"}:
            continue
        relative = literal(call.args[0])
        path = ROOT / relative
        text = texts.setdefault(relative, path.read_text(encoding="utf-8"))
        anchor = literal(call.args[1])
        count = text.count(anchor)
        preview = anchor.splitlines()[0][:120]
        if count != 1:
            raise SystemExit(
                f"{script.name}:{node.lineno}: {relative}: expected one anchor, "
                f"found {count}: {preview!r}"
            )
        if name == "replace_once":
            replacement = literal(call.args[2])
            text = text.replace(anchor, replacement, 1)
        else:
            addition = literal(call.args[2])
            text = text.replace(anchor, addition + anchor, 1)
        texts[relative] = text

print(f"validated {len(texts)} recovery target files")
Path(__file__).unlink()
