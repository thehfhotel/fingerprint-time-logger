# Schedule-Based Punch Classification Plan

## Overview
Replace ZK device punch_type dependency with work schedule-based logic to determine check-in/check-out status.

## Current State Analysis

**ZK Device Dependency**: 
- `record.punch` (0-5) directly determines check-in/check-out
- Device logic controls punch classification
- Inconsistent mapping in codebase (0=check-in vs 0,1=check-in)

**Work Schedule System**:
- Standard schedules: Fixed daily times + working days
- Shift schedules: Multiple shifts with daily assignments  
- Monthly overrides: Custom work days per month
- Real-time validation already exists

## Milestone #1: Core Classification Engine

### 1.1 New Check-in/Check-out Logic Engine

**Core Algorithm**:
```
For each attendance record:
1. Get employee's active schedule for punch date
2. Find expected work period (start_time to end_time)  
3. Look at employee's previous punches for that day
4. Determine punch intent:
   - First punch near start_time = CHECK_IN
   - Next punch near end_time = CHECK_OUT
   - Handle break punches, overtime, etc.
```

### 1.2 Schedule-Based Punch Classifier (`app/services/punch_classifier.py`)
```python
class PunchClassifier:
    def classify_punch(employee_id, timestamp, raw_punch_type):
        schedule = get_active_schedule(employee_id, timestamp.date())
        previous_punches = get_daily_punches(employee_id, timestamp.date())
        
        return determine_punch_type(schedule, timestamp, previous_punches)
```

**Classification Rules**:
1. **First punch within work period** → CHECK_IN
2. **Subsequent punch near end time** → CHECK_OUT  
3. **Multiple punches** → Alternate IN/OUT pattern
4. **Outside work hours** → Overtime or irregular
5. **Break times** → BREAK_OUT/BREAK_IN (if configured)

## Milestone #2: Data Model Enhancement

### 2.1 Data Model Changes (`app/models.py`)

**Preserve raw device data**:
```python
class AttendanceRecord:
    # Existing fields...
    punch_type = Integer              # Keep original device punch_type
    raw_device_punch = Integer        # NEW: Store original ZK punch value
    classified_punch_type = String    # NEW: Schedule-determined type
    classification_confidence = Float # NEW: Algorithm confidence (0-1)
    classification_method = String    # NEW: 'SCHEDULE_BASED', 'DEVICE_LEGACY'
```

### 2.2 Database Migration
- Add new fields without breaking existing schema
- Preserve all historical data
- Create indexes for performance

## Milestone #3: Device Service Integration

### 3.1 Enhanced Device Service (`app/services/device_service.py`)

**Modified sync process**:
1. Fetch raw attendance from ZK device (unchanged)
2. Store raw `punch_type` as `raw_device_punch`
3. **NEW**: Run classification algorithm
4. Store classified result in `classified_punch_type`
5. Use classified type for all application logic

### 3.2 Schedule Integration Points

#### A. Standard Schedule Logic
- Use `WorkSchedule.start_time/end_time` as reference points
- Check `working_days` for valid work days
- Apply `EmployeeMonthlySchedule` overrides if exists

#### B. Shift Schedule Logic  
- Get daily shift from `ReceptionShiftAssignment`
- Handle overnight shifts (`is_overnight = True`)
- Use shift-specific start/end times

#### C. Grace Period & Tolerance
- **Early punch tolerance**: 30 minutes before start_time
- **Late punch tolerance**: 60 minutes after start_time  
- **End time tolerance**: ±30 minutes around end_time
- Configurable thresholds per job role

## Milestone #4: Edge Case Handling

### 4.1 Multiple Punches Per Day
```
Timeline approach:
09:00 (near start) → CHECK_IN
12:00 (break time) → BREAK_OUT  
13:00 (break time) → BREAK_IN
17:00 (near end)   → CHECK_OUT
```

### 4.2 Irregular Punches
- **Before work hours**: Early arrival (still CHECK_IN)
- **After work hours**: Overtime (CHECK_OUT with OT flag)
- **Non-work days**: Manual review required

### 4.3 Missing Schedule Data
- **Fallback**: Use previous week's pattern
- **Default**: Standard 8:00-17:00 if no schedule exists
- **Flag**: Mark records for manual review

## Milestone #5: Backward Compatibility

### 5.1 Legacy Support Mode
- **Environment flag**: `USE_DEVICE_PUNCH_TYPE=true/false`
- **Gradual migration**: Both methods available during transition
- **Data preservation**: Keep all original device data

### 5.2 API Compatibility
- **Response format**: Unchanged for existing endpoints
- **New fields**: Optional in API responses
- **Filter support**: New filters for classification confidence

## Milestone #6: Configuration & Admin Controls

### 6.1 Classification Settings (`app/config/classification.py`)
```python
CLASSIFICATION_SETTINGS = {
    'early_tolerance_minutes': 30,
    'late_tolerance_minutes': 60,
    'end_time_tolerance_minutes': 30,
    'enable_break_detection': True,
    'enable_overtime_detection': True,
    'min_confidence_threshold': 0.7
}
```

### 6.2 Admin Interface Updates
- **Classification review page**: View low-confidence records
- **Override capability**: Manual punch type correction
- **Batch operations**: Reclassify date ranges
- **Report generation**: Classification accuracy metrics

## Milestone #7: Testing & Validation

### 7.1 Unit Tests
- **Schedule matching**: Various time scenarios  
- **Edge cases**: Missing schedules, overlapping shifts
- **Data integrity**: Ensure no data loss

### 7.2 Integration Tests  
- **End-to-end flow**: Device → Classification → Database
- **API compatibility**: Existing endpoint responses
- **Performance**: Classification speed with large datasets

### 7.3 Validation Tests
- **Historical analysis**: Run on past 3 months of data
- **Accuracy measurement**: Compare with manual classification
- **Edge case coverage**: Non-standard work patterns

## Milestone #8: Deployment Strategy

### 8.1 Phase 1: Implementation (No Breaking Changes)
1. Add new classification service
2. Add new database fields
3. Store both device and classified punch types
4. Use device punch type for all logic (existing behavior)

### 8.2 Phase 2: Testing & Validation
1. Run classification algorithm on historical data
2. Compare classified vs device punch types
3. Identify discrepancies and edge cases
4. Tune classification rules

### 8.3 Phase 3: Switchover
1. Enable schedule-based classification
2. Monitor for issues
3. Provide manual override for problematic records
4. Keep device data as fallback

## Milestone #9: Rollback Plan

### 9.1 Quick Rollback
- **Feature flag**: Instant switch back to device punch types
- **Data safety**: Original device data preserved
- **Zero downtime**: No database schema changes required

### 9.2 Full Rollback
- **Remove new fields**: Optional cleanup migration
- **Code removal**: Classification service removal
- **Documentation**: Updated to reflect rollback

---

## Breaking Change Analysis

### Potential Breaking Changes ❌
1. **API response changes**: If new fields are required
2. **Database schema**: New required columns
3. **Business logic dependencies**: Code expecting device punch types

### Mitigation Strategies ✅
1. **Additive changes only**: New fields are optional
2. **Feature flags**: Gradual rollout with instant rollback
3. **Backward compatibility**: Preserve all existing APIs
4. **Data preservation**: Never modify original device data

---

## Implementation Order

1. **Milestone #1**: Core Classification Engine
2. **Milestone #2**: Data Model Enhancement  
3. **Milestone #3**: Device Service Integration
4. **Milestone #4**: Edge Case Handling
5. **Milestone #5**: Backward Compatibility
6. **Milestone #6**: Configuration & Admin Controls
7. **Milestone #7**: Testing & Validation
8. **Milestone #8**: Deployment Strategy
9. **Milestone #9**: Rollback Plan

**Success Criteria**: 
- Zero breaking changes to existing functionality
- Improved accuracy in punch classification
- Maintainable and configurable classification logic
- Complete data preservation and rollback capability