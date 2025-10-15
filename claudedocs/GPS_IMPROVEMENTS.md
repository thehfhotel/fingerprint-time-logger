# GPS Accuracy Improvements for Mobile QR Check-in

## Problem Statement

When users' phones connect to WiFi, the browser's Geolocation API was using **WiFi-based positioning** (SSID database lookup) instead of **GPS satellite positioning**, resulting in:
- Low accuracy (100-500m) that failed backend validation (≤50m required)
- Poor user experience with rejected check-in attempts
- No visibility into whether GPS or WiFi positioning was being used

## Root Cause

**Previous GPS Configuration:**
```javascript
{
    enableHighAccuracy: true,
    maximumAge: 10000,  // Too permissive - allowed cached WiFi positions
    timeout: 5000       // Too short - GPS satellite lock takes 10-15s from cold start
}
```

The short timeout caused the browser to fallback to faster WiFi-based positioning when GPS satellite lock wasn't immediately available.

## Solution Implemented

### 1. Enhanced GPS Configuration

**File:** `static/js/mobile-checkin.js` (lines 238-242)

```javascript
{
    enableHighAccuracy: true,  // Request phone GPS (not WiFi)
    maximumAge: 5000,          // Force fresh GPS readings (↓ from 10000ms)
    timeout: 15000             // Allow GPS satellite lock (↑ from 5000ms)
}
```

**Changes:**
- ⬇️ **maximumAge: 10000ms → 5000ms** - Reject stale WiFi-based positions
- ⬆️ **timeout: 5000ms → 15000ms** - Wait for GPS satellite lock

### 2. Client-Side Accuracy Validation

**File:** `static/js/mobile-checkin.js` (lines 48-49, 167-169)

```javascript
// GPS accuracy requirement (stricter than backend 50m)
const GPS_REQUIRED_ACCURACY = 30; // meters

function isGPSAccurate(accuracy) {
    return accuracy <= GPS_REQUIRED_ACCURACY;
}
```

**Purpose:**
- Enforce 30m accuracy threshold (stricter than backend 50m)
- Prevent check-in attempts with poor GPS accuracy
- Ensure phone GPS (not WiFi) is being used

### 3. Dynamic Scanner Button State

**File:** `static/js/mobile-checkin.js` (lines 174-210)

```javascript
function updateGPSStatus(position) {
    const accuracy = Math.round(position.coords.accuracy);

    if (isGPSAccurate(accuracy)) {
        // Good GPS lock - enable scanner
        elements.gpsText.textContent = 'GPS พร้อมใช้งาน ✓';
        elements.gpsText.style.color = '#28a745'; // Green
        elements.startScanButton.disabled = false;
        console.log(`[GPS] Good accuracy: ${accuracy}m (GPS lock)`);
    } else {
        // Waiting for GPS - disable scanner
        elements.gpsText.textContent = 'กำลังรอสัญญาณ GPS...';
        elements.gpsText.style.color = '#ffc107'; // Yellow
        elements.startScanButton.disabled = true;
        console.log(`[GPS] Waiting: ${accuracy}m > 30m (likely WiFi)`);
    }
}
```

**Features:**
- Real-time GPS status updates with color coding
- Scanner button disabled until GPS accuracy achieved
- Console logging distinguishes GPS vs WiFi positioning

### 4. Initial Button State

**File:** `static/mobile-checkin.html` (line 71)

```html
<button id="startScanButton" class="control-btn primary" disabled>
    📷 เริ่มสแกน
</button>
```

**Purpose:** Scanner starts disabled, enabled only when GPS accuracy is sufficient

## Expected Behavior

### Before Implementation
```
1. Open app → WiFi positioning used (±150m)
2. "GPS ready ✓" shown (misleading)
3. Scan QR → Backend rejects (accuracy > 50m)
4. User confused ❌
```

### After Implementation
```
1. Open app → "กำลังรอสัญญาณ GPS... ±150m" (yellow)
2. Wait 5-15 seconds for GPS satellite lock
3. "GPS พร้อมใช้งาน ✓ ±18m" (green)
4. Scanner enabled → Scan QR → Success ✓
```

## Technical Details

### GPS Positioning Timeline

**Cold Start (No Recent GPS Data):**
```
0-5s:   Acquiring satellites → WiFi fallback (100-500m)
5-10s:  Partial GPS lock → Improving accuracy (50-100m)
10-15s: Full GPS lock → High accuracy (5-30m) ✓
```

**Warm Start (Recent GPS Data):**
```
0-3s:   Quick GPS reacquisition → High accuracy (5-30m) ✓
```

### Accuracy Thresholds

| Source | Typical Accuracy | Status |
|--------|------------------|--------|
| WiFi Positioning | 100-500m | ❌ Too inaccurate |
| Cell Tower | 500-5000m | ❌ Too inaccurate |
| GPS (Partial Lock) | 30-100m | ⚠️ Acceptable for some cases |
| GPS (Full Lock) | 5-30m | ✓ Recommended |

**System Thresholds:**
- Frontend requirement: ≤30m (forces GPS lock)
- Backend validation: ≤50m (allows marginal GPS)
- WiFi positioning: Usually 100-500m (rejected)

## Console Logging

### GPS Lock Achieved (Good)
```
[GPS] Starting GPS tracking with high-accuracy phone GPS mode...
[GPS] Good accuracy achieved: 18m (GPS lock)
[GPS] Good accuracy achieved: 15m (GPS lock)
```

### Waiting for GPS (WiFi Positioning)
```
[GPS] Starting GPS tracking with high-accuracy phone GPS mode...
[GPS] Waiting for better accuracy: 150m > 30m (likely WiFi)
[GPS] Waiting for better accuracy: 85m > 30m (likely WiFi)
[GPS] Good accuracy achieved: 22m (GPS lock)
```

## Testing Recommendations

### Test Scenarios

1. **WiFi Connected (Indoor)**
   - Expected: Yellow status for 5-15 seconds
   - Then: Green status when GPS locks
   - Scanner: Disabled → Enabled when ready

2. **WiFi Disconnected (Outdoor)**
   - Expected: Green status within 5-10 seconds
   - GPS: Faster acquisition without WiFi interference

3. **Poor GPS Signal (Indoor)**
   - Expected: Yellow status persists
   - Scanner: Remains disabled
   - User: Should move outdoors or near window

4. **Good GPS Signal (Outdoor)**
   - Expected: Green status within 3-5 seconds
   - Scanner: Quickly enabled
   - Check-in: Should succeed

### Validation Steps

1. Open mobile check-in page with WiFi enabled
2. Observe GPS status: Should show "กำลังรอสัญญาณ GPS..."
3. Watch accuracy values decrease over 5-15 seconds
4. Verify scanner button becomes enabled when accuracy ≤30m
5. Attempt check-in: Should succeed with GPS coordinates

## Impact

### User Experience
- ✅ Clear GPS status feedback (color-coded)
- ✅ Prevents wasted check-in attempts with poor accuracy
- ✅ Reduced confusion about GPS vs WiFi positioning
- ✅ Better guidance on when system is ready

### Technical
- ✅ Forces phone GPS over WiFi positioning
- ✅ Reduces backend validation failures
- ✅ Improved check-in success rate
- ✅ Better debugging with detailed console logs

### Performance
- ⏱️ 5-15 second wait for GPS lock (acceptable trade-off)
- 📊 Higher accuracy: 5-30m (GPS) vs 100-500m (WiFi)
- ✓ Check-in success rate improvement expected

## Future Enhancements (Not Implemented)

### Medium Priority
1. **GPS Help Card** - Show guidance when GPS unavailable
2. **Visual Threshold Indicator** - Show "Need ≤30m" requirement
3. **Force Refresh Button** - Manual GPS reacquisition

### Low Priority
4. **Positioning Source Detection** - Explicitly detect GPS vs WiFi
5. **Accuracy History Graph** - Show GPS acquisition progress
6. **Smart Timeout** - Adaptive timeout based on environment

## Files Modified

```
static/js/mobile-checkin.js
├── Line 48-49: Add GPS_REQUIRED_ACCURACY constant
├── Line 167-169: Add isGPSAccurate() function
├── Line 174-210: Add updateGPSStatus() function
├── Line 215-244: Rewrite startGPSTracking() function
└── Line 238-242: Update GPS options

static/mobile-checkin.html
└── Line 71: Add disabled attribute to scanner button
```

## References

- **Geolocation API:** https://developer.mozilla.org/en-US/docs/Web/API/Geolocation_API
- **enableHighAccuracy:** Hints browser to prefer GPS over WiFi/cell tower
- **maximumAge:** Maximum age of cached position (0 = always fresh)
- **timeout:** Maximum time to wait for position acquisition

## Commit Information

**Type:** improve
**Scope:** GPS positioning accuracy for mobile QR check-in
**Summary:** Force phone GPS over WiFi positioning with accuracy validation

**Changes:**
- Enhanced GPS configuration (timeout: 15s, maximumAge: 5s)
- Client-side accuracy validation (≤30m requirement)
- Dynamic scanner button state based on GPS accuracy
- Real-time status feedback with color coding
