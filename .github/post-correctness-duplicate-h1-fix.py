from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "crates/controller-api/src/worker/tests/reconnect.rs"
text = TARGET.read_text(encoding="utf-8")
start = "struct MatchingSession {\n"
end = "#[test]\nfn mismatched_native_frame_never_reaches_connected() {\n"
if text.count(start) != 1:
    raise SystemExit(f"expected one redundant MatchingSession block, found {text.count(start)}")
if text.count(end) != 1:
    raise SystemExit(f"expected one mismatch-test anchor, found {text.count(end)}")
if text.count("fn matching_native_frame_positive_control_reaches_connected()") != 2:
    raise SystemExit("expected exactly two positive-control tests before cleanup")
begin = text.index(start)
finish = text.index(end, begin)
text = text[:begin] + text[finish:]
if text.count("fn matching_native_frame_positive_control_reaches_connected()") != 1:
    raise SystemExit("positive-control cleanup did not leave exactly one test")
if "struct MatchingFrameSession {" not in text:
    raise SystemExit("existing matching-frame positive-control fixture was removed")
TARGET.write_text(text, encoding="utf-8")
for temporary in (
    ROOT / ".github/post-correctness-duplicate-h1-fix.py",
    ROOT / ".github/workflows/post-correctness-fixup.yml",
):
    temporary.unlink()
