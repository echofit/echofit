.PHONY: install test clean

install:
	@echo "Installing echofit packages in editable mode..."
	pip install -e sdk/ -e mcp/

test:
	@echo "Running tests..."
	pytest

clean:
	rm -rf build dist *.egg-info sdk/*.egg-info mcp/*.egg-info
	find . -name "__pycache__" -type d -exec rm -rf {} +