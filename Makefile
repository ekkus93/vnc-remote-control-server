SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c

.PHONY: fmt lint test build compose-up compose-down integration-test e2e-test security-scan

fmt:
	cargo fmt --all --check

lint:
	cargo clippy --workspace --all-targets --all-features -- -D warnings

test:
	cargo test --workspace --all-features

build:
	cargo build --workspace --all-features --locked

compose-up:
	docker compose -f deploy/compose.yaml up --build --detach --wait

compose-down:
	docker compose -f deploy/compose.yaml down --volumes --remove-orphans

integration-test:
	./tests/integration/run.sh

e2e-test:
	./tests/e2e/run.sh

security-scan:
	cargo deny check
