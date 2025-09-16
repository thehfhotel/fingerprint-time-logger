# Security Testing Framework for Fingerprint Time Logger

Comprehensive security testing framework specifically designed for biometric time tracking systems with Thai localization support.

## Overview

This security testing framework provides comprehensive coverage for the fingerprint time logger system, addressing unique security challenges in biometric systems, Thai Unicode handling, and real-time WebSocket communications.

## Framework Components

### 1. **Biometric Security Testing** (`test_biometric_security.py`)
- **Biometric Data Protection**: Tests for fingerprint template exposure and biometric data leakage
- **ZKTeco Device Security**: Device communication security, configuration injection
- **Attendance Record Integrity**: Timestamp tampering, record manipulation detection
- **Employee ID Enumeration**: Protection against employee information disclosure

### 2. **WebSocket Security Testing** (`test_websocket_security.py`)
- **Message Injection Attacks**: XSS, command injection, SQL injection via WebSocket
- **Broadcast Security**: Sanitization of real-time update data
- **Connection Security**: DoS protection, connection limits, rate limiting
- **Protocol Security**: WebSocket handshake security, message validation

### 3. **CSV Injection & Export Security** (`test_csv_injection.py`)
- **Formula Injection**: Excel/LibreOffice formula injection attacks (=cmd, +cmd, @SUM)
- **Data Exposure**: Mass data extraction, sensitive information leakage
- **File Download Security**: Content-Type, Content-Disposition, cache headers
- **Parameter Injection**: Export parameter tampering and injection

### 4. **API Endpoint Security** (`test_api_security.py`)
- **Input Validation**: Comprehensive injection testing (SQL, XSS, Command, Path Traversal)
- **Rate Limiting**: DoS protection, request flooding prevention
- **CORS Configuration**: Cross-origin request security
- **Security Headers**: CSP, X-Frame-Options, X-XSS-Protection validation
- **ZKTeco Integration**: Device configuration security, sync data validation

### 5. **Unicode & Internationalization Security** (`test_unicode_security.py`)
- **Thai Character Security**: Thai Unicode injection, encoding bypass
- **Unicode Normalization**: Homograph attacks, visual spoofing
- **Mixed Script Injection**: Multi-language script injection attacks
- **Bidirectional Text**: RTL override attacks, text direction manipulation
- **Character Encoding**: UTF-8, UTF-16 bypass attempts

### 6. **Automated Security Tools** (`test_automated_security_tools.py`)
- **Static Analysis**: Bandit integration for code security scanning
- **Dependency Scanning**: Safety integration for vulnerable dependency detection
- **Custom SAST**: Pattern-based security vulnerability detection
- **Dependency Audit**: Version-based vulnerability assessment

## Quick Start

### Running Security Tests

```bash
# Run all security tests
pytest tests/security/ -v

# Run specific security category
pytest tests/security/test_biometric_security.py -v
pytest tests/security/test_websocket_security.py -v
pytest tests/security/test_csv_injection.py -v

# Run comprehensive security assessment
python tests/security/security_test_runner.py --full

# Generate threat model
python tests/security/security_test_runner.py --threat-model

# Quick security scan
python tests/security/security_test_runner.py --quick
```

### Running with pytest markers

```bash
# Run only security tests
pytest -m security

# Run security tests excluding slow ones
pytest tests/security/ -v --ignore=slow_tests/
```

## Security Test Categories

### 🔒 **Critical Security Areas Tested**

1. **Biometric Data Protection**
   - Fingerprint template exposure prevention
   - Biometric data leakage in API responses
   - Device communication security

2. **Input Validation & Injection Prevention**
   - SQL injection (all endpoints)
   - XSS (reflected and stored)
   - Command injection
   - Path traversal
   - Template injection
   - CSV formula injection

3. **Authentication & Authorization**
   - Authentication bypass attempts
   - Session security
   - Privilege escalation

4. **Data Protection**
   - PII (Thai names, badge numbers) protection
   - Information disclosure prevention
   - Error message sanitization

5. **Communication Security**
   - WebSocket security
   - API endpoint security
   - CORS configuration
   - Security headers

6. **Internationalization Security**
   - Thai Unicode handling
   - Character encoding security
   - Mixed script injection prevention

## Test Configuration

### Environment Setup

Create `.env.test` file:
```env
DATABASE_URL=sqlite:///./test_security.db
ZKTECO_HOST=192.168.100.209
ZKTECO_PORT=4370
TESTING=true
```

### Pytest Configuration

Add to `pytest.ini`:
```ini
[tool:pytest]
markers =
    security: marks tests as security tests
    slow: marks tests as slow running
    biometric: marks tests as biometric specific
    websocket: marks tests as websocket specific
    unicode: marks tests as unicode/i18n specific

testpaths = tests
python_files = test_*.py
python_functions = test_*
python_classes = Test*

# Security test specific configuration
addopts = --strict-markers --tb=short
filterwarnings =
    ignore::DeprecationWarning
    ignore::PendingDeprecationWarning
```

## Security Reporting

### Report Generation

The framework generates multiple types of security reports:

1. **HTML Reports**: Human-readable security assessment reports
2. **JSON Reports**: Machine-readable data for CI/CD integration
3. **Threat Models**: STRIDE-based threat modeling documents
4. **Vulnerability Summaries**: Categorized vulnerability listings

### Report Locations

```
security_reports/
├── security_assessment_YYYYMMDD_HHMMSS.html
├── security_assessment_YYYYMMDD_HHMMSS.json
├── threat_model_YYYYMMDD_HHMMSS.json
├── bandit_security_report.html
└── comprehensive_security_report.html
```

### CI/CD Integration

```yaml
# Example GitHub Actions integration
- name: Security Testing
  run: |
    python tests/security/security_test_runner.py --full --json-only
    # Exit with error code if critical/high vulnerabilities found

- name: Upload Security Reports
  uses: actions/upload-artifact@v2
  with:
    name: security-reports
    path: security_reports/
```

## Threat Model

### System Components
- **FastAPI Web Server**: API endpoints, static file serving
- **SQLite Database**: Employee, device, attendance data storage
- **ZKTeco Integration**: Biometric device communication
- **WebSocket System**: Real-time attendance updates
- **CSV Export System**: Data export functionality
- **Thai Localization**: Unicode text handling

### Security Boundaries
- Web Client ↔ FastAPI Server
- FastAPI Server ↔ SQLite Database
- FastAPI Server ↔ ZKTeco Device
- Client ↔ WebSocket Connection

### Key Assets Protected
- Employee biometric data (fingerprint templates)
- Personal information (Thai names, badge numbers)
- Attendance records and timestamps
- ZKTeco device configurations
- System configuration data

## Biometric-Specific Security Considerations

### 1. **Biometric Template Protection**
- Templates never exposed in API responses
- Device communication encryption
- Template storage security

### 2. **Attendance Data Integrity**
- Timestamp validation and range checking
- Record tampering detection
- Audit trail maintenance

### 3. **Employee Privacy**
- Thai name PII protection
- Badge number enumeration prevention
- Personal data export restrictions

### 4. **Device Security**
- ZKTeco device authentication
- Configuration parameter validation
- Communication channel security

## Unicode & Thai Localization Security

### 1. **Character Encoding Security**
- UTF-8 validation and normalization
- Thai character injection prevention
- Mixed script attack prevention

### 2. **Visual Spoofing Prevention**
- Homograph attack detection
- Unicode normalization enforcement
- Bidirectional text security

### 3. **Export Security**
- CSV Thai character handling
- Formula injection in Thai text
- Encoding consistency validation

## Advanced Security Features

### 1. **Dynamic Security Testing**
- Real-time vulnerability assessment
- Adaptive test payload generation
- Context-aware security validation

### 2. **Fuzzing Integration**
- Input fuzzing for all API endpoints
- WebSocket message fuzzing
- File format fuzzing for exports

### 3. **Performance Security**
- DoS attack simulation
- Resource exhaustion testing
- Rate limiting validation

## Security Test Development Guidelines

### 1. **Test Structure**
```python
class SecurityTester(SecurityTester):
    async def test_specific_vulnerability(self) -> List[SecurityVulnerability]:
        vulnerabilities = []
        # Test implementation
        return vulnerabilities
```

### 2. **Vulnerability Reporting**
```python
SecurityVulnerability(
    id="unique_vulnerability_id",
    title="Descriptive Vulnerability Title",
    description="Detailed description",
    severity=SecurityLevel.HIGH,
    category="Vulnerability Category",
    endpoint="/api/endpoint",
    payload="test payload",
    recommendation="Fix recommendation",
    cwe="CWE-XXX"
)
```

### 3. **Test Categories**
- **Critical**: System compromise, data breach potential
- **High**: Significant security impact, requires immediate attention
- **Medium**: Security weakness, should be addressed soon
- **Low**: Minor security improvement, address when convenient

## Integration with Existing Tests

### Running with Regular Tests
```bash
# Run all tests including security
pytest

# Run only non-security tests
pytest --ignore=tests/security/

# Run security tests with coverage
pytest tests/security/ --cov=app --cov-report=html
```

### Pre-commit Hooks
```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: security-tests
        name: Security Tests
        entry: python tests/security/security_test_runner.py --quick
        language: python
        pass_filenames: false
        always_run: true
```

## Troubleshooting

### Common Issues

1. **Test Database Setup**
   - Ensure test database is properly initialized
   - Check database permissions and paths

2. **ZKTeco Device Mocking**
   - Device tests use mocked responses
   - Real device testing requires network configuration

3. **Unicode Test Issues**
   - Ensure proper UTF-8 terminal support
   - Check locale settings for Thai character display

4. **WebSocket Testing**
   - TestClient WebSocket support may be limited
   - Consider using real WebSocket connections for advanced testing

### Performance Optimization

1. **Parallel Test Execution**
   ```bash
   pytest tests/security/ -n auto  # Requires pytest-xdist
   ```

2. **Selective Test Running**
   ```bash
   pytest tests/security/ -k "not slow"
   ```

3. **Caching**
   - Security scan results are cached between runs
   - Clear cache with `pytest --cache-clear`

## Security Tool Dependencies

### Required Security Tools
```bash
pip install bandit[toml]  # Static security analysis
pip install safety        # Dependency vulnerability scanning
pip install pytest-security  # Security-focused pytest extensions
```

### Optional Tools
```bash
pip install semgrep      # Advanced SAST scanning
pip install pip-audit    # Python package auditing
pip install vulners     # Vulnerability database integration
```

## Contributing to Security Tests

### Adding New Security Tests

1. **Create test file** in appropriate category
2. **Follow naming convention**: `test_[category]_security.py`
3. **Implement SecurityTester** subclass
4. **Add comprehensive docstrings** explaining security focus
5. **Include vulnerability examples** in test cases
6. **Add integration** to security_test_runner.py

### Security Test Best Practices

1. **Comprehensive Coverage**: Test all attack vectors for each component
2. **Real-world Payloads**: Use actual attack payloads, not just theory
3. **Context Awareness**: Consider system-specific attack scenarios
4. **Clear Reporting**: Provide actionable vulnerability reports
5. **Performance Consideration**: Balance thoroughness with execution time

## Security Contact

For security issues or questions about the security testing framework:

- **Security Issues**: Report via secure channel (not public issues)
- **Framework Questions**: Use project discussion forums
- **Contributions**: Follow standard PR process with security review

---

**Note**: This security testing framework is specifically designed for the Fingerprint Time Logger system's unique requirements including biometric data handling, Thai localization, and ZKTeco device integration. Regular updates and maintenance are required to address emerging security threats.