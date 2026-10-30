PYTHON ?= python3
PYTHONPATH := .
PACKAGES := topology controller experiments
ROOT_SOURCES := topo.py route_controller.py phase1_validate.py analyze_results.py

.PHONY: test syntax unit synthetic

test: syntax unit

syntax:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q $(PACKAGES) $(ROOT_SOURCES)

unit:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -p "test_*.py" -v

synthetic:
	$(PYTHON) synthetic_demo/generate_synthetic_data.py
	$(PYTHON) synthetic_demo/analyze_synthetic_data.py
