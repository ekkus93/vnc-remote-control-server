from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "crates/controller-api/src/config.rs"
text = path.read_text(encoding="utf-8")
old = "    pub(crate) fn from_secret(secret: SecretString) -> Self {\n"
new = "    pub fn from_secret(secret: SecretString) -> Self {\n"
if text.count(old) != 1:
    raise SystemExit("config.rs: explicit ApiToken constructor anchor missing or duplicated")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
(ROOT / ".github/post-correctness-recovery-api-fix.py").unlink()
