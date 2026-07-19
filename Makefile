.PHONY: hooks checkpoint check test-backend test-scanner test-frontend test-rust crash-wrap new-issue migrate

## Install git hooks (run once per clone)
hooks:
	@bash scripts/install-hooks.sh

## Run all checks + commit + optionally push: make checkpoint ARGS="--push"
checkpoint:
	@bash scripts/checkpoint.sh $(ARGS)

## Run the same checks as pre-commit, without committing
check: test-backend test-scanner test-frontend test-rust

test-backend:
	@echo "── backend imports ──"
	@.venv/bin/python -c "from papis.main import app; print('OK —', len(app.routes), 'routes')"
	@PYTHONPATH=backend:. .venv/bin/python -c "from daemon.papis_daemon import main; print('OK — daemon')"

## Run the scanner/bulk-scan test suite (pytest)
test-scanner:
	@echo "── scanner test suite ──"
	@cd backend && $(CURDIR)/.venv/bin/python -m pytest -q

test-frontend:
	@echo "── frontend types ──"
	@cd frontend && npx tsc --noEmit && echo "OK"

test-rust:
	@echo "── rust check ──"
	@cd src-tauri && cargo check --quiet && echo "OK"

## Run the app wrapped in crash-log capture: make crash-wrap
crash-wrap:
	@bash scripts/run-with-crash-log.sh

## Append a templated entry to TROUBLESHOOTING.md: make new-issue TITLE="..."
new-issue:
	@bash scripts/new-issue.sh "$(TITLE)"

## Apply pending Alembic migrations (startup no longer does this automatically)
migrate:
	@echo "── running alembic upgrade head ──"
	@cd backend && $(CURDIR)/.venv/bin/alembic upgrade head && echo "✓ database at head"
