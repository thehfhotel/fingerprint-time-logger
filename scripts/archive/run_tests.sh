#!/bin/bash
# Comprehensive test script for Fingerprint Time Logger

echo "=== Fingerprint Time Logger Test Suite ==="
echo "Starting test execution with coverage reporting..."

# Activate virtual environment
source venv/bin/activate

# Run tests with different markers
echo ""
echo "1. Running unit tests..."
python -m pytest tests/test_api.py tests/test_config.py tests/test_models.py tests/test_services.py -m "not performance" --cov-report=term-missing

echo ""
echo "2. Running integration tests (API routers)..."
python -m pytest tests/unit/ -m "not performance" --cov-append --cov-report=term-missing

echo ""
echo "3. Generating final coverage reports..."
python -m pytest --cov-report=html --cov-report=xml --cov-report=term

echo ""
echo "=== Test Summary ==="
echo "Coverage reports generated:"
echo "- HTML: htmlcov/index.html"
echo "- XML: coverage.xml"
echo "- Terminal: Above output"

echo ""
echo "=== Coverage Quality Gates ==="
python -c "
import xml.etree.ElementTree as ET
import os

if os.path.exists('coverage.xml'):
    tree = ET.parse('coverage.xml')
    root = tree.getroot()
    coverage = float(root.attrib['line-rate']) * 100
    print(f'Current coverage: {coverage:.1f}%')

    if coverage >= 85:
        print('✅ EXCELLENT: Coverage >= 85%')
        exit(0)
    elif coverage >= 75:
        print('✅ GOOD: Coverage >= 75%')
        exit(0)
    elif coverage >= 60:
        print('⚠️  ACCEPTABLE: Coverage >= 60%')
        exit(0)
    else:
        print('❌ NEEDS IMPROVEMENT: Coverage < 60%')
        exit(1)
else:
    print('⚠️  Coverage report not found')
    exit(1)
"