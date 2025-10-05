# Test Plan: Persistent Login & Smart OAuth Features

## Overview

This test plan covers the new persistent login and smart OAuth callback features implemented for the LINE authentication system.

## Features Under Test

### 1. Persistent Login
- JWT token remains in localStorage after successful account linking
- Users stay logged in across sessions
- Token contains employee_badge for linked accounts

### 2. Smart OAuth Callback
- Checks if LINE user is already linked to an employee
- **Linked users**: Redirect to mobile check-in with employee_badge in JWT
- **Unlinked users**: Redirect to link-account page for 6-digit code entry

### 3. Auto-redirect for Linked Accounts
- If user visits link-account page with already-linked JWT, auto-redirect to mobile check-in
- Prevents re-linking for already-linked accounts

### 4. Token Update After Linking
- After successful linking, new JWT token with employee_badge is saved to localStorage
- Frontend updates token before redirect

### 5. Enhanced verify-token Response
- Returns structured response with `employee_badge` and `line_profile`
- Mobile check-in uses this to determine if account is linked

---

## Test Suite Structure

```
tests/
├── unit/
│   └── test_line_auth_persistent_login.py          # Backend logic tests
├── integration/
│   └── test_oauth_flow_persistent_login.py         # Full flow tests
├── e2e/
│   └── test_persistent_login_ui.py                 # User journey tests
└── security/
    └── test_token_security_persistent_login.py     # Security tests
```

---

## 1. Backend Unit Tests

**File**: `tests/unit/test_line_auth_persistent_login.py`

### Test Cases

#### 1.1 OAuth Callback - Linked User
```python
def test_oauth_callback_linked_user_redirects_to_mobile(db_session):
    """
    GIVEN: LINE user already linked to employee
    WHEN: OAuth callback is processed
    THEN: JWT contains employee_badge AND redirects to /qr-checkin/mobile
    """
```

#### 1.2 OAuth Callback - Unlinked User
```python
def test_oauth_callback_unlinked_user_redirects_to_link_account(db_session):
    """
    GIVEN: LINE user not linked to any employee
    WHEN: OAuth callback is processed
    THEN: JWT has employee_badge=None AND redirects to /qr-checkin/link-account
    """
```

#### 1.3 Verify Token - Linked Account Structure
```python
def test_verify_token_returns_employee_badge_for_linked(db_session):
    """
    GIVEN: JWT token with employee_badge
    WHEN: /verify-token endpoint is called
    THEN: Response includes employee_badge and line_profile structure
    """
```

#### 1.4 Verify Token - Unlinked Account Structure
```python
def test_verify_token_returns_null_badge_for_unlinked(db_session):
    """
    GIVEN: JWT token without employee_badge
    WHEN: /verify-token endpoint is called
    THEN: Response has employee_badge=None and line_profile structure
    """
```

#### 1.5 Link Account - Token Update
```python
def test_link_account_returns_new_token_with_badge(db_session):
    """
    GIVEN: Valid linking code and unlinked JWT
    WHEN: /link-account endpoint is called
    THEN: New JWT token with employee_badge is returned
    """
```

---

## 2. Integration Tests

**File**: `tests/integration/test_oauth_flow_persistent_login.py`

### Test Cases

#### 2.1 Full OAuth Flow - Linked User
```python
async def test_full_oauth_flow_linked_user_skips_linking(test_client, db_session):
    """
    GIVEN: Employee with linked LINE account exists
    WHEN: User completes LINE OAuth flow
    THEN:
      - User is redirected to /qr-checkin/mobile
      - JWT token contains employee_badge
      - No linking step required
    """
```

#### 2.2 Full OAuth Flow - Unlinked User
```python
async def test_full_oauth_flow_unlinked_user_requires_linking(test_client, db_session):
    """
    GIVEN: New LINE user (not linked)
    WHEN: User completes LINE OAuth flow
    THEN:
      - User is redirected to /qr-checkin/link-account
      - JWT token has employee_badge=None
      - Linking code entry required
    """
```

#### 2.3 Token Persistence Across Requests
```python
async def test_jwt_token_validates_across_multiple_requests(test_client, db_session):
    """
    GIVEN: Valid JWT token with employee_badge
    WHEN: Multiple API calls use the same token
    THEN: All requests succeed with consistent employee data
    """
```

#### 2.4 Link-Account Token Update Flow
```python
async def test_linking_updates_token_with_employee_badge(test_client, db_session):
    """
    GIVEN: Unlinked JWT and valid linking code
    WHEN: User submits linking code
    THEN:
      - New JWT with employee_badge is returned
      - Employee record updated with LINE user_id
      - Subsequent verify-token calls return employee_badge
    """
```

---

## 3. E2E Tests (Playwright)

**File**: `tests/e2e/test_persistent_login_ui.py`

### Test Cases

#### 3.1 First-Time User Journey
```python
async def test_first_time_user_linking_journey(page, browser):
    """
    Scenario: New user links LINE account for first time

    Steps:
      1. User clicks "Login with LINE" on mobile-checkin page
      2. LINE OAuth completes (mock or real)
      3. User is redirected to link-account page
      4. Admin generates 6-digit code
      5. User enters linking code
      6. Success message shown for 2 seconds
      7. User redirected to mobile check-in
      8. Scanner interface displayed
      9. Verify localStorage contains JWT with employee_badge

    Assertions:
      - JWT token in localStorage
      - employee_badge present in token payload
      - Scanner section visible
      - Profile displays employee badge number
    """
```

#### 3.2 Returning Linked User Journey
```python
async def test_returning_linked_user_skips_linking(page, browser):
    """
    Scenario: User with linked account returns

    Steps:
      1. Set up: Link account in previous session
      2. User visits /qr-checkin/mobile directly
      3. Page loads with JWT from localStorage
      4. Scanner interface shows immediately

    Assertions:
      - No login prompt shown
      - Scanner visible on page load
      - Profile shows correct employee data
    """
```

#### 3.3 OAuth Auto-Login for Linked User
```python
async def test_oauth_login_linked_user_skips_code_entry(page, browser):
    """
    Scenario: Linked user logs in via LINE OAuth

    Steps:
      1. User clicks "Login with LINE"
      2. LINE OAuth completes
      3. User automatically redirected to mobile check-in (NOT link-account)
      4. Scanner shows immediately

    Assertions:
      - Never sees link-account page
      - JWT in localStorage has employee_badge
      - Scanner interface ready
    """
```

#### 3.4 Link-Account Auto-Redirect
```python
async def test_link_account_page_redirects_if_already_linked(page, browser):
    """
    Scenario: Linked user accidentally visits link-account page

    Steps:
      1. Set up: User has linked JWT in localStorage
      2. User navigates to /qr-checkin/link-account
      3. Page detects linked token
      4. Auto-redirect to mobile check-in

    Assertions:
      - Redirect happens within 1 second
      - Console shows "Account already linked" message
      - Final page is mobile check-in with scanner
    """
```

#### 3.5 LocalStorage Token Persistence
```python
async def test_jwt_token_persists_across_page_reloads(page, browser):
    """
    Scenario: Verify token survives page reloads

    Steps:
      1. User completes linking
      2. Reload /qr-checkin/mobile page
      3. Reload again
      4. Close browser and reopen
      5. Navigate to /qr-checkin/mobile

    Assertions:
      - Token still in localStorage after each reload
      - Scanner shows without re-login
      - No authentication prompts
    """
```

#### 3.6 iOS Safari Specific Test
```python
async def test_ios_safari_oauth_redirect_behavior(page, browser):
    """
    Scenario: iOS Safari LINE OAuth flow (uses Safari regardless of default browser)

    Steps:
      1. Simulate iOS Safari user agent
      2. Click "Login with LINE"
      3. LINE OAuth opens in Safari
      4. OAuth callback returns
      5. User sees appropriate page based on link status

    Assertions:
      - Redirect URLs work correctly in iOS Safari
      - JWT token saved to localStorage
      - Meta refresh redirects function properly
    """
```

---

## 4. Security Tests

**File**: `tests/security/test_token_security_persistent_login.py`

### Test Cases

#### 4.1 JWT Token Expiration
```python
def test_expired_token_rejected_by_verify_endpoint():
    """
    GIVEN: Expired JWT token
    WHEN: /verify-token is called
    THEN: 401 Unauthorized returned
    """
```

#### 4.2 Invalid Token Signature
```python
def test_tampered_token_rejected():
    """
    GIVEN: JWT token with modified payload but valid structure
    WHEN: /verify-token is called
    THEN: 401 Unauthorized returned
    """
```

#### 4.3 Token Contains Expected Claims
```python
def test_jwt_token_contains_required_claims():
    """
    GIVEN: Valid JWT token
    WHEN: Token is decoded
    THEN: Contains line_user_id, employee_badge, display_name, picture_url, iat, exp
    """
```

#### 4.4 CSRF State Token Validation
```python
def test_oauth_callback_validates_state_token():
    """
    GIVEN: OAuth callback with invalid state token
    WHEN: Callback endpoint is called
    THEN: 400 Bad Request returned
    """
```

#### 4.5 Token Refresh Security
```python
def test_linking_generates_new_token_not_modifies_old():
    """
    GIVEN: Unlinked JWT token
    WHEN: Account is linked
    THEN: New JWT generated with different signature (not modified old token)
    """
```

---

## Test Execution

### Run All Tests
```bash
# All test suites
./scripts/test-suite-console.sh all

# Specific categories
./scripts/test-suite-console.sh unit
./scripts/test-suite-console.sh integration
./scripts/test-suite-console.sh e2e
./scripts/test-suite-console.sh security
```

### Run Specific Test File
```bash
# Backend unit tests
python3 -m pytest tests/unit/test_line_auth_persistent_login.py -v

# Integration tests
python3 -m pytest tests/integration/test_oauth_flow_persistent_login.py -v

# E2E tests
python3 -m pytest tests/e2e/test_persistent_login_ui.py -v --headed

# Security tests
python3 -m pytest tests/security/test_token_security_persistent_login.py -v
```

### Run with Coverage
```bash
python3 -m pytest tests/ --cov=app.api.line_auth --cov=app.services.line_auth_service --cov-report=html
```

---

## Success Criteria

### Unit Tests
- ✅ All OAuth callback logic paths tested
- ✅ verify-token response structure validated
- ✅ Token creation with/without employee_badge covered
- ✅ 100% coverage of modified line_auth.py code

### Integration Tests
- ✅ Full OAuth flows for linked and unlinked users
- ✅ Token persistence across multiple requests
- ✅ Database state correctly updated after linking

### E2E Tests
- ✅ All user journeys complete successfully
- ✅ LocalStorage token handling verified
- ✅ Auto-redirect scenarios work correctly
- ✅ iOS Safari specific behavior validated

### Security Tests
- ✅ Token validation enforced
- ✅ Expired/invalid tokens rejected
- ✅ CSRF protection verified
- ✅ No security regressions

---

## Known Edge Cases

### 1. Token Expiry During Session
**Scenario**: User's JWT expires while using the app
**Expected**: Logout and re-authenticate
**Test**: `test_expired_token_triggers_reauth`

### 2. Concurrent Linking Attempts
**Scenario**: Same LINE user tries to link to multiple employees
**Expected**: Later link overwrites earlier link
**Test**: `test_concurrent_linking_uses_latest`

### 3. Browser LocalStorage Disabled
**Scenario**: User has localStorage disabled
**Expected**: Fallback to session-only login (no persistence)
**Test**: `test_no_localstorage_fallback`

### 4. LINE Profile Update
**Scenario**: User changes LINE display name/picture
**Expected**: New OAuth login updates profile in JWT
**Test**: `test_oauth_updates_line_profile_data`

---

## Test Data Requirements

### Database Setup
```python
# Linked employee fixture
@pytest.fixture
def linked_employee(db_session):
    employee = Employee(
        badge_number="12345",
        display_name="Test Employee",
        line_user_id="U1234567890abcdef",
        line_display_name="LINE User",
        line_picture_url="https://example.com/pic.jpg"
    )
    db_session.add(employee)
    db_session.commit()
    return employee

# Unlinked employee fixture
@pytest.fixture
def unlinked_employee(db_session):
    employee = Employee(
        badge_number="67890",
        display_name="Unlinked Employee",
        line_user_id=None,
        line_linking_code="123456",
        line_linking_code_generated_at=datetime.now(timezone.utc)
    )
    db_session.add(employee)
    db_session.commit()
    return employee
```

### Mock LINE OAuth Responses
```python
@pytest.fixture
def mock_line_oauth_response():
    return {
        "access_token": "mock_access_token_12345",
        "token_type": "Bearer",
        "expires_in": 2592000,
        "refresh_token": "mock_refresh_token_67890"
    }

@pytest.fixture
def mock_line_profile():
    return {
        "userId": "U1234567890abcdef",
        "displayName": "Test LINE User",
        "pictureUrl": "https://profile.line-scdn.net/test123",
        "statusMessage": "Hello from LINE"
    }
```

---

## Test Maintenance

### When to Update Tests

1. **OAuth Flow Changes**: Update integration and E2E tests
2. **JWT Token Structure Changes**: Update unit tests and security tests
3. **Frontend UI Changes**: Update E2E selectors and assertions
4. **New Features Added**: Add corresponding test cases

### Test Review Checklist

- [ ] All new features have corresponding tests
- [ ] Edge cases identified and tested
- [ ] Security implications tested
- [ ] iOS/mobile-specific behavior validated
- [ ] Test coverage >90% for modified code
- [ ] All tests pass in CI/CD pipeline
- [ ] Test documentation updated

---

## Automated Testing Strategy

### Pre-commit Hooks
```bash
# Run unit tests before commit
python3 -m pytest tests/unit/ -q
```

### CI/CD Pipeline
```yaml
stages:
  - unit_tests: Run all unit tests
  - integration_tests: Run integration tests with test database
  - e2e_tests: Run Playwright E2E tests (headless)
  - security_tests: Run security validation tests
  - coverage_report: Generate and publish coverage report
```

### Continuous Monitoring
- Track test execution time trends
- Monitor flaky tests and stabilize
- Review test coverage reports weekly
- Update tests when bugs are found in production
