#!/usr/bin/env python3
"""Apply compile repairs discovered by the first R10 runtime validation run."""

from pathlib import Path

cargo = Path("crates/controller-api/Cargo.toml")
content = cargo.read_text(encoding="utf-8")
old = "tokio.workspace = true\n\n[dev-dependencies]\ntower.workspace = true\n"
new = "tokio.workspace = true\ntower.workspace = true\n\n[dev-dependencies]\n"
if content.count(old) != 1:
    raise SystemExit("controller-api tower dependency layout did not match")
cargo.write_text(content.replace(old, new, 1), encoding="utf-8")

runtime = Path("crates/controller-api/src/runtime.rs")
content = runtime.read_text(encoding="utf-8")
old = "use tower::ServiceExt;"
new = "use tower::util::ServiceExt;"
if content.count(old) != 1:
    raise SystemExit("runtime ServiceExt import did not match")
runtime.write_text(content.replace(old, new, 1), encoding="utf-8")

Path(__file__).unlink()
