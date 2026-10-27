APPS := veille-marches content-engine avis-clients newsletter-pipeline
UV ?= uv

.PHONY: setup test lint $(addprefix setup-,$(APPS)) $(addprefix test-,$(APPS)) run-veille

setup: $(addprefix setup-,$(APPS))

setup-%:
	@if [ -d apps/$* ]; then \
		cd apps/$* && $(UV) venv .venv >/dev/null && $(UV) pip install -q -e ../../packages/core -e ".[dev]" && echo "ok  apps/$*"; \
	else echo "skip apps/$* (absent)"; fi

test: $(addprefix test-,$(APPS))

test-%:
	@if [ -x apps/$*/.venv/bin/pytest ]; then \
		cd apps/$* && .venv/bin/pytest -q; \
	else echo "skip apps/$* (pas de venv : make setup-$*)"; fi

test-core:
	cd packages/core && $(UV) venv .venv >/dev/null && $(UV) pip install -q -e ".[dev]" && .venv/bin/pytest -q

lint:
	@for a in packages/core $(addprefix apps/,$(APPS)); do \
		if [ -d $$a ]; then (cd $$a && [ -x .venv/bin/ruff ] && .venv/bin/ruff check . || true); fi; \
	done

run-veille:
	cd apps/veille-marches && .venv/bin/vm collect --dry-run && .venv/bin/vm digest --dry-run
