#!/bin/bash
set -e

echo "===================================="
echo "Executing wd-qtr-gsi-builder maven-deploy.sh"
echo "===================================="

python3 -m pip install poetry==2.1.2 twine --index-url "https://artifactory.us.caas.oneadp.com/artifactory/api/pypi/pypi/simple"
poetry config repositories.adp https://artifactory.us.caas.oneadp.com/artifactory/api/pypi/pypi/simple

rm -rf dist/

poetry build -f wheel
python3 -m twine upload --repository-url \
    https://artifactory.us.caas.oneadp.com/artifactory/api/pypi/cs-pypi \
    -u "${ARTIFACTORY_USER}" -p "${ARTIFACTORY_PASSWORD}" dist/*.whl

rm -f maven_test_executed.flag
echo "===================================="
echo "wd-qtr-gsi-builder maven-deploy: DONE"
echo "===================================="
