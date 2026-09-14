PYTHON ?= python
.PHONY: setup refresh report check preview collect archive backup validate
setup refresh report check preview collect archive backup:
	$(PYTHON) make.py $@
validate:
	$(PYTHON) scripts/validate_report.py
