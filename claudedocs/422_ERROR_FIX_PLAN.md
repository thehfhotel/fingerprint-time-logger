# 422 Error Investigation & Fix Plan

## Investigation Summary

### Issue Discovery
Three test failures identified in complete test suite:
1. **422 Error**: `/api/admin/line-codes/stats` returning 422 instead of expected 200/401/403
2. **Fixture Scope Mismatch**: `test_qr_terminal_realtime.py` has fixture scope errors
3. **Page Title Mismatch**: `test_individual_attendance.py` expects wrong title

### Root Cause Analysis

#### 1. 422 Error - `/api/admin/line-codes/stats`
**File**: `app/api/admin_line_codes.py:426-463`

**Endpoint Definition**:
```python
@router.get("/stats")
async def get_linking_stats(
    passcode: str,  # ← REQUIRED query parameter
    db: Session = Depends(get_db)
):
    verify_admin_passcode(passcode)
    # ... returns statistics
```

**Problem**:
- Endpoint requires `passcode` as query parameter
- Test calls endpoint without passcode: `api_client.get("/api/admin/line-codes/stats")`
- FastAPI validation fails → 422 Unprocessable Entity

**Why 422 Happens**:
- 422 = Request understood but validation failed
- Missing required parameter `passcode` triggers Pydantic validation error
- This is expected behavior for missing required parameters

#### 2. Fixture Scope Mismatch - test_qr_terminal_realtime.py
**Error**: `ScopeMismatch: You tried to access the function scoped fixture base_url with a session scoped request object`

**Problem**:
- `conftest.py` has `base_url` as function-scoped fixture
- `test_qr_terminal_realtime.py` likely has session-scoped fixture trying to use it
- Scope conflict causes all 12 tests to error

#### 3. Page Title Mismatch - test_individual_attendance.py
**Expected**: `"เข้า/ออก รายคน - Individual Attendance"`
**Actual**: `"เข้า/ออก รายคน - การลงเวลารายบุคคล"`

**Problem**: Test expects English subtitle but page uses Thai subtitle

---

## Fix Plan

### Phase 1: Commit Current State (Before Fix)
**Action**: Commit existing test fixes from previous work
**Files**:
- tests/e2e/test_individual_attendance.py
- tests/e2e/test_line_oauth_flow.py
- tests/e2e/test_line_persistent_login.py
- tests/e2e/test_qr_terminal_realtime.py

**Commit Message**: "test: Fix E2E test issues (URL paths, localStorage, element visibility)"

---

### Phase 2: Fix 422 Error - Admin Line Codes Stats
**File**: `tests/e2e/test_qr_checkin_ui.py:237-241`

**Current Code**:
```python
def test_admin_line_codes_api_accessible(self, api_client, app_running):
    """Test that Admin Line Codes API is accessible"""
    response = api_client.get("/api/admin/line-codes/stats")
    # Should return 401/403 without auth, 422 for validation errors, or 200 with valid auth
    assert response.status_code in [200, 401, 403, 422]
```

**Problem**: Test doesn't provide required `passcode` parameter

**Solution Options**:

**Option A: Test with valid passcode (RECOMMENDED)**
```python
def test_admin_line_codes_api_accessible(self, api_client, app_running):
    """Test that Admin Line Codes API returns stats with valid passcode"""
    response = api_client.get(
        "/api/admin/line-codes/stats",
        params={"passcode": "bananabananabanana"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "total_active_employees" in data
    assert "linked_accounts" in data
    assert "pending_codes" in data
    assert "unlinked" in data
```

**Option B: Test without passcode expects 422**
```python
def test_admin_line_codes_api_requires_passcode(self, api_client, app_running):
    """Test that Admin Line Codes API requires passcode"""
    response = api_client.get("/api/admin/line-codes/stats")
    assert response.status_code == 422  # Missing required parameter
```

**Option C: Test both scenarios**
```python
def test_admin_line_codes_stats_requires_passcode(self, api_client, app_running):
    """Test that stats endpoint requires passcode"""
    # Without passcode → 422
    response = api_client.get("/api/admin/line-codes/stats")
    assert response.status_code == 422

def test_admin_line_codes_stats_with_invalid_passcode(self, api_client, app_running):
    """Test that stats endpoint rejects invalid passcode"""
    response = api_client.get(
        "/api/admin/line-codes/stats",
        params={"passcode": "wrong"}
    )
    assert response.status_code == 403

def test_admin_line_codes_stats_success(self, api_client, app_running):
    """Test that stats endpoint works with valid passcode"""
    response = api_client.get(
        "/api/admin/line-codes/stats",
        params={"passcode": "bananabananabanana"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "total_active_employees" in data
```

**Recommendation**: Use **Option C** for comprehensive coverage

---

### Phase 3: Fix Fixture Scope Mismatch
**File**: `tests/e2e/test_qr_terminal_realtime.py`

**Investigation Needed**: Find where fixture scope is defined

**Likely Fix**: Remove custom `base_url` fixture definition from test file if it exists, or change scope to match conftest.py

**Search**:
```bash
grep -n "@pytest.fixture" tests/e2e/test_qr_terminal_realtime.py
```

---

### Phase 4: Fix Page Title Assertion
**File**: `tests/e2e/test_individual_attendance.py:38`

**Current Code**:
```python
expect(page).to_have_title("เข้า/ออก รายคน - Individual Attendance")
```

**Fix**:
```python
expect(page).to_have_title("เข้า/ออก รายคน - การลงเวลารายบุคคล")
```

---

### Phase 5: Verify All Fixes
**Action**: Run complete test suite
```bash
./scripts/run-complete-test-suite.sh
```

**Success Criteria**:
- All 20 test categories pass
- 0 failures
- 100% pass rate

---

### Phase 6: Commit & Push After Fix
**Files Modified**:
- tests/e2e/test_qr_checkin_ui.py (422 fix)
- tests/e2e/test_qr_terminal_realtime.py (fixture scope fix)
- tests/e2e/test_individual_attendance.py (title fix)

**Commit Message**: "test: Fix 422 error, fixture scope mismatch, and page title assertion"

**Push**: `git push origin main`

---

## Implementation Order

1. ✅ Investigation complete
2. ⏭️ Commit current state (before fix)
3. ⏭️ Fix 422 error with comprehensive test coverage
4. ⏭️ Fix fixture scope mismatch
5. ⏭️ Fix page title assertion
6. ⏭️ Run complete test suite
7. ⏭️ Commit and push fixes

---

## Additional Notes

### Why This Wasn't Caught Earlier
- Previous test run showed these as "PASSED" categories despite internal errors
- Test script marks category as passed if exit code is 0
- Some tests had errors but didn't fail the category
- Need better test reporting to surface errors vs failures

### Browser Console 422 Errors (Production)
**Status**: UNRELATED to test fixes

The production 422 errors from browser console are from:
- `https://erp.thehfhotel.org/fingerprintlogs/api/devices/app-config`
- `https://erp.thehfhotel.org/fingerprintlogs/api/devices/time`

These are production application issues, NOT caused by test changes. Separate investigation needed.
