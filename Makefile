.PHONY: install test clean

install:
	@echo "Installing food-agent in editable mode..."
	pip install -e .

test:
	@echo "Running tests..."
	export PYTHONPATH=. && pytest

clean:
	rm -rf build dist *.egg-info
	find . -name "__pycache__" -type d -exec rm -rf {} +