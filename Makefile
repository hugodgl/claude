APPS := veille-marches content-engine avis-clients newsletter-pipeline
UV ?= uv
SETUP_TARGETS := $(addprefix setup-,$(APPS))
TEST_TARGETS := $(addprefix test-,$(APPS))

.PHONY: setup test lint test-core run-veille $(SETUP_TARGETS) $(TEST_TARGETS)

setup: $(SETUP_TARGETS)

$(SETUP_TARGETS): setup-%:
	@if [ -d apps/$* ]; then \
		cd apps/$* && { [ -d .venv ] || $(UV) venv .venv >/dev/null; } && $(UV) pip install -q -e ../../packages/core -e ".[dev]" && echo "ok  apps/$*"; \
	else echo "skip apps/$* (absent)"; fi

test: test-core $(TEST_TARGETS)

$(TEST_TARGETS): test-%:
	@if [ -x apps/$*/.venv/bin/pytest ]; then \
		echo "== apps/$* ==" && cd apps/$* && .venv/bin/pytest -q; \
	else echo "skip apps/$* (pas de venv : make setup-$*)"; fi

test-core:
	@cd packages/core && { [ -d .venv ] || $(UV) venv .venv >/dev/null; } && $(UV) pip install -q -e ".[dev]" && echo "== packages/core ==" && .venv/bin/pytest -q

lint:
	@for a in packages/core $(addprefix apps/,$(APPS)); do \
		if [ -x $$a/.venv/bin/ruff ]; then echo "== $$a ==" && (cd $$a && .venv/bin/ruff check .); fi; \
	done

run-veille:
	cd apps/veille-marches && .venv/bin/vm collect --dry-run && .venv/bin/vm digest --dry-run
