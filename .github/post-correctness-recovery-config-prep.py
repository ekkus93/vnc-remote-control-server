from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "crates/controller-api/src/config.rs"
MAIN = ROOT / ".github/post-correctness-recovery.py"
BOUNDARY = ROOT / ".github/post-correctness-recovery-boundary-fix.py"
API_FIX = ROOT / ".github/post-correctness-recovery-api-fix.py"


def replace_between(text: str, start: str, end: str, replacement: str) -> str:
    if text.count(start) != 1:
        raise SystemExit(f"config structural start anchor mismatch: {start!r}")
    begin = text.index(start)
    try:
        finish = text.index(end, begin + len(start))
    except ValueError as error:
        raise SystemExit(
            f"config structural end anchor missing after start: {start!r} / {end!r}"
        ) from error
    return text[:begin] + replacement + text[finish:]


def remove_target_calls(script: Path, target: str) -> None:
    source = script.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(script))
    lines = source.splitlines(keepends=True)
    removals: list[tuple[int, int]] = []
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not isinstance(call.func, ast.Name) or call.func.id not in {
            "replace_once",
            "insert_before_once",
        }:
            continue
        if not call.args:
            continue
        try:
            relative = ast.literal_eval(call.args[0])
        except (ValueError, TypeError):
            continue
        if relative == target:
            removals.append((node.lineno - 1, node.end_lineno or node.lineno))
    if not removals:
        raise SystemExit(f"{script.name}: no calls target {target}")
    for start_line, end_line in reversed(removals):
        del lines[start_line:end_line]
    script.write_text("".join(lines), encoding="utf-8")


text = CONFIG.read_text(encoding="utf-8")
text = replace_between(
    text,
    "/// Process-wide API bearer token.",
    "/// Fully validated process configuration.",
    '''/// Process-wide API bearer token. The value is intentionally not `Debug` or
/// `Display`; cloning this handle clones an `Arc`, not the token bytes.
#[derive(Clone, PartialEq, Eq)]
pub struct ApiToken {
    inner: Arc<SecretString>,
}

impl ApiToken {
    /// Transfers one parsed file-backed secret into long-lived token ownership.
    pub fn from_secret(secret: SecretString) -> Self {
        Self {
            inner: Arc::new(secret),
        }
    }

    /// Exposes bytes only to the constant-time bearer comparison boundary.
    pub(crate) fn as_bytes(&self) -> &[u8] {
        self.inner.expose_secret().as_bytes()
    }

    /// Returns whether this token would be unusable for authentication.
    pub(crate) fn is_empty(&self) -> bool {
        self.inner.expose_secret().is_empty()
    }

    #[cfg(test)]
    fn expose_secret_for_test(&self) -> &str {
        self.inner.expose_secret()
    }
}

''',
)
old_load = "let api_token = ApiToken::new(secrets.read_secret(&api_token_path)?);"
if text.count(old_load) != 1:
    raise SystemExit("config API-token load anchor mismatch")
text = text.replace(
    old_load,
    "let api_token = ApiToken::from_secret(secrets.read_secret(&api_token_path)?);",
    1,
)
text = replace_between(
    text,
    "fn parse_secret_bytes_with_rejection_observer<F>(",
    "#[cfg(unix)]",
    '''fn parse_secret_bytes_with_rejection_observer<F>(
    path: &Path,
    mut bytes: Vec<u8>,
    observe_rejection: F,
) -> Result<SecretString, ConfigError>
where
    F: FnOnce(&[u8]),
{
    if std::str::from_utf8(&bytes).is_err() {
        return scrub_and_reject_secret_bytes(
            path,
            bytes,
            "contents are not UTF-8",
            observe_rejection,
        );
    }

    let mut trimmed_length = bytes.len();
    while trimmed_length > 0 && matches!(bytes[trimmed_length - 1], b'\n' | b'\r') {
        trimmed_length -= 1;
    }
    if trimmed_length == 0 || bytes[..trimmed_length].contains(&0) {
        return scrub_and_reject_secret_bytes(
            path,
            bytes,
            "contents are empty or contain NUL",
            observe_rejection,
        );
    }

    secure_scrub_bytes(&mut bytes[trimmed_length..]);
    bytes.truncate(trimmed_length);
    match String::from_utf8(bytes) {
        Ok(value) => Ok(SecretString::from(value)),
        Err(error) => scrub_and_reject_secret_bytes(
            path,
            error.into_bytes(),
            "contents are not UTF-8",
            observe_rejection,
        ),
    }
}

fn scrub_and_reject_secret_bytes<F>(
    path: &Path,
    mut bytes: Vec<u8>,
    reason: &'static str,
    observe_rejection: F,
) -> Result<SecretString, ConfigError>
where
    F: FnOnce(&[u8]),
{
    secure_scrub_bytes(&mut bytes);
    observe_rejection(&bytes);
    Err(ConfigError::SecretFile {
        path: path.to_path_buf(),
        reason,
    })
}

fn secure_scrub_bytes(bytes: &mut [u8]) {
    scrub_secret_bytes(bytes);
}

''',
)
old_import = "use libvnc_adapter::{NativeClientConfig, SecretString};"
if text.count(old_import) != 1:
    raise SystemExit("config libvnc import anchor mismatch")
text = text.replace(
    old_import,
    "use libvnc_adapter::{scrub_secret_bytes, NativeClientConfig, SecretString};",
    1,
)
atomic_import = "use std::sync::atomic::{Ordering, compiler_fence};\n"
if text.count(atomic_import) != 1:
    raise SystemExit("config atomic import anchor mismatch")
text = text.replace(atomic_import, "", 1)
old_assertion = 'assert_eq!(config.api_token.as_ref(), "api-token");'
if text.count(old_assertion) != 1:
    raise SystemExit("config API-token assertion anchor mismatch")
text = text.replace(
    old_assertion,
    'assert_eq!(config.api_token.expose_secret_for_test(), "api-token");',
    1,
)
CONFIG.write_text(text, encoding="utf-8")

remove_target_calls(MAIN, "crates/controller-api/src/config.rs")
remove_target_calls(BOUNDARY, "crates/controller-api/src/config.rs")
API_FIX.unlink()
Path(__file__).unlink()
