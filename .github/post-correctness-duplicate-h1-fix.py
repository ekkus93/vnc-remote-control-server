from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Remove the redundant positive control introduced by the recovery helper while
# preserving the pre-existing adjacent matching-frame control.
reconnect = ROOT / "crates/controller-api/src/worker/tests/reconnect.rs"
text = reconnect.read_text(encoding="utf-8")
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
reconnect.write_text(text, encoding="utf-8")

# Keep ServerEvent deliberately non-PartialEq; assert only the error variant.
events = ROOT / "crates/controller-api/src/events.rs"
text = events.read_text(encoding="utf-8")
old = '''        assert_eq!(first, Err(EventSequenceError::Exhausted));
        assert_eq!(second, Err(EventSequenceError::Exhausted));
'''
new = '''        assert!(matches!(first, Err(EventSequenceError::Exhausted)));
        assert!(matches!(second, Err(EventSequenceError::Exhausted)));
'''
if text.count(old) != 1:
    raise SystemExit(f"events.rs: expected one exhaustion assertion block, found {text.count(old)}")
events.write_text(text.replace(old, new, 1), encoding="utf-8")

# HttpState now requires the explicit secret-bearing ApiToken type. Update the
# remaining validation fixtures rather than restoring raw-string conversions.
access = ROOT / "crates/controller-api/src/http/tests/access_log_and_validation.rs"
text = access.read_text(encoding="utf-8")
empty = '            Arc::from(""),\n'
token = '            Arc::from("token"),\n'
if text.count(empty) != 1:
    raise SystemExit(f"access-log tests: expected one empty-token fixture, found {text.count(empty)}")
if text.count(token) != 3:
    raise SystemExit(f"access-log tests: expected three token fixtures, found {text.count(token)}")
text = text.replace(
    empty,
    '            ApiToken::from_secret(SecretString::from("")),\n',
    1,
)
text = text.replace(
    token,
    '            ApiToken::from_secret(SecretString::from("token")),\n',
)
access.write_text(text, encoding="utf-8")

for temporary in (
    ROOT / ".github/post-correctness-duplicate-h1-fix.py",
    ROOT / ".github/workflows/post-correctness-fixup.yml",
):
    temporary.unlink()
