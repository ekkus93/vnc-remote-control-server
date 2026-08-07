SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c

PYTHON_LINT_PATHS := python/src/vnc_remote_control tests scripts tools/ci_status desktop/test-app

.PHONY: fmt lint lint-python lint-python-ruff lint-python-pylint lint-python-mypy test build compose-up compose-down integration-test e2e-test security-scan

fmt:
	cargo fmt --all --check

lint:
	cargo clippy --workspace --all-targets --all-features -- -D warnings

lint-python: lint-python-ruff lint-python-pylint lint-python-mypy

lint-python-ruff:
	ruff check .

lint-python-pylint:
	pylint --rcfile=.pylintrc $(PYTHON_LINT_PATHS)

lint-python-mypy:
	mypy --config-file mypy.ini $(PYTHON_LINT_PATHS)

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
