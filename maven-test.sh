#!/bin/bash
set +e

echo "===================================="
echo "wd-qtr-gsi-builder maven-test.sh execution: START"
echo "===================================="

WORKSPACE="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$WORKSPACE"

FLAG_FILE="maven_test_executed.flag"

if [ ! -f "$FLAG_FILE" ]; then
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -name "*.pyc" -delete 2>/dev/null || true

    if ! command -v poetry &> /dev/null; then
        echo "Poetry not found. Installing Poetry..."
        python3 -m pip install poetry==2.1.2 --index-url "https://artifactory.us.caas.oneadp.com/artifactory/api/pypi/cs-pypi/simple" --timeout 60 --retries 5
        if [ $? -ne 0 ]; then
            echo "Poetry installation failed, retrying with different approach..."
            python3 -m pip install --upgrade pip
            python3 -m pip install poetry==2.1.2 --index-url "https://artifactory.us.caas.oneadp.com/artifactory/api/pypi/cs-pypi/simple" --timeout 120 --retries 3
        fi
        poetry config repositories.adp https://artifactory.us.caas.oneadp.com/artifactory/api/pypi/pypi/simple
    else
        echo "Poetry already installed: $(poetry --version)"
    fi

    poetry lock --no-update || true
    poetry config installer.max-workers 1
    poetry config installer.timeout 300
    poetry install --with dev
    install_exit_code=$?

    if [ $install_exit_code -ne 0 ]; then
        echo "Poetry install failed, falling back to pip..."
        python3 -m pip install -r requirements.txt --timeout 120 --retries 3
    fi

    echo "BEGIN: Running Tests"
    if command -v poetry &> /dev/null && [ $install_exit_code -eq 0 ]; then
        poetry run pytest tests/ --cov=src --cov-report=xml --cov-report=term-missing
        exit_code=$?
        if [ $exit_code -ne 0 ]; then
            echo "Coverage failed, running basic tests..."
            poetry run pytest tests/
            exit_code=$?
        fi
    else
        echo "Running tests with pip-installed dependencies..."
        python3 -m pytest tests/ --cov=src --cov-report=xml --cov-report=term-missing
        exit_code=$?
        if [ $exit_code -ne 0 ]; then
            echo "Coverage failed, running basic tests..."
            python3 -m pytest tests/
            exit_code=$?
        fi
    fi
    echo "END: Running Tests - Exit Code: ${exit_code}"
    if [ -f "$(pwd)/coverage.xml" ]; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|<source>.*</source>|<source>$(pwd)/src</source>|g" "$(pwd)/coverage.xml"
        else
            sed -i "s|<source>.*</source>|<source>$(pwd)/src</source>|g" "$(pwd)/coverage.xml"
        fi
    fi
    touch "$FLAG_FILE"
else
    echo "maven-test.sh has already been executed. Skipping execution."
    exit_code=0
fi

echo "===================================="
echo "wd-qtr-gsi-builder maven-test.sh execution: DONE"
echo "===================================="

exit $exit_code
