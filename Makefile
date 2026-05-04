.PHONY: farm-cli.pyz clean-cli help

PY ?= python3
PIP ?= $(PY) -m pip

help:
	@echo "Targets:"
	@echo "  farm-cli.pyz    build dist/farm-cli.pyz (self-contained CLI)"
	@echo "  clean-cli       remove the local CLI build outputs"
	@echo ""
	@echo "Note: the docker image already builds farm-cli.pyz inside the"
	@echo "cli-builder stage and serves it from GET /install/farm-cli."
	@echo "Use this Makefile when you want a local copy without docker."

# Self-contained farm-cli zipapp. Requires only python3 + pip on the host.
# Result is one file at dist/farm-cli.pyz. Drop it on a client machine,
# chmod +x, run.
farm-cli.pyz:
	rm -rf build/cli-pyz dist/farm-cli.pyz
	mkdir -p build/cli-pyz dist
	$(PIP) install --quiet --target build/cli-pyz ./client
	find build/cli-pyz -name '*.dist-info' -prune -exec rm -rf {} +
	find build/cli-pyz -name '__pycache__' -prune -exec rm -rf {} +
	$(PY) -m zipapp build/cli-pyz \
		--output dist/farm-cli.pyz \
		--main "farm_cli.cli:cli" \
		--python "/usr/bin/env python3" \
		--compress
	@echo
	@echo "built: dist/farm-cli.pyz ($$(du -h dist/farm-cli.pyz | cut -f1))"
	@echo "test:  ./dist/farm-cli.pyz --help"

clean-cli:
	rm -rf build/cli-pyz dist/farm-cli.pyz
