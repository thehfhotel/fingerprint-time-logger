# GPS Location Setup for QR Terminals

Complete guide for configuring GPS locations for main office and branch offices with **Leaflet + OpenStreetMap** (Free, No API Key Required).

## Overview

The GPS location feature allows administrators to:
- Set GPS coordinates for each QR terminal location
- Define validation radius for check-in verification
- Distinguish between main office and branch offices
- Use embedded interactive maps for easy location selection
- Validate employee check-ins are within authorized areas

## Features

✅ **Visual Location Selection** - Click on interactive map to set GPS coordinates
✅ **Multiple Office Support** - Main office and branch office designation
✅ **Adjustable Radius** - 50m to 500m validation range
✅ **Draggable Markers** - Click and drag to fine-tune location
✅ **Real-time Preview** - Visual radius circle on map
✅ **Persistent Storage** - GPS data saved in device metadata
✅ **Completely Free** - No API key, no usage limits, no cost
✅ **Open Source** - Powered by Leaflet + OpenStreetMap

## Prerequisites

### No API Key Required! 🎉

This system uses **Leaflet** (open-source JavaScript library) with **OpenStreetMap** tiles (free map data).

**Advantages:**
- ✅ **Zero Cost** - Completely free with no usage limits
- ✅ **No Registration** - No need to create accounts or get API keys
- ✅ **No Quotas** - Unlimited map loads and interactions
- ✅ **Privacy Friendly** - No data sent to third-party services
- ✅ **Open Source** - Community-driven and transparent

**What You Need:**
- ✅ Modern web browser (Chrome, Firefox, Safari, Edge)
- ✅ Internet connection (to load map tiles)
- ✅ That's it!

## Setup Instructions

### Step 1: Create QR Terminal Device

Before setting GPS location, create a QR terminal device:

1. Use Device Management or direct database insert:

```sql
INSERT INTO devices (name, ip_address, port, device_type, is_active)
VALUES ('QR Terminal - Main Office', '192.168.1.100', 4370, 'qr_terminal', true);
```

2. Or use API endpoint (if available):

```bash
POST /api/devices/
{
  "name": "QR Terminal - Branch 1",
  "ip_address": "192.168.1.101",
  "port": 4370,
  "device_type": "qr_terminal",
  "is_active": true
}
```

### Step 2: Access GPS Admin Page

Navigate to the GPS management interface:

```
http://localhost:5000/fingerprintlogs/admin/terminal-gps
```

Or in production:
```
https://your-domain.com/fingerprintlogs/admin/terminal-gps
```

### Step 3: Select Terminal

From the left sidebar:
1. Click on the terminal you want to configure
2. Terminal card will highlight and show current GPS status
3. If GPS is not configured, you'll see: ⚠️ ยังไม่ได้ตั้งค่า GPS

### Step 4: Set GPS Location

**Method 1: Click on Map**
1. Click anywhere on the Google Map
2. Marker will appear at clicked location
3. GPS coordinates auto-populate in form fields

**Method 2: Search Location**
1. Type location name in "ชื่อสถานที่" field
2. Google Places autocomplete suggests locations
3. Select location from dropdown
4. Map centers on selected location

**Method 3: Drag Marker**
1. After setting initial location, drag the marker
2. GPS coordinates update in real-time

### Step 5: Configure Settings

**Office Type:**
- 🏢 **สำนักงานใหญ่** (Main Office) - Primary office location
- 🏪 **สาขา** (Branch) - Branch office location

**Location Name:**
- Descriptive name for the location
- Example: "สำนักงานใหญ่ (กรุงเทพฯ)", "สาขาเชียงใหม่"

**Validation Radius:**
- Adjust slider from 50m to 500m
- Purple circle shows validation area on map
- Employees must be within this radius to check in

### Step 6: Save Location

1. Review GPS coordinates and settings
2. Click **💾 บันทึกตำแหน่ง** (Save Location)
3. Success message confirms save
4. Terminal list updates with GPS icon

## Data Structure

GPS location data is stored in the `device_metadata` JSON field:

```json
{
  "gps": {
    "latitude": 13.756331,
    "longitude": 100.501765,
    "radius": 200,
    "location_name": "สำนักงานใหญ่ (กรุงเทพฯ)",
    "office_type": "main",
    "updated_at": "2025-01-10T14:30:00Z"
  }
}
```

### Fields Explained

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `latitude` | float | GPS latitude in decimal degrees | 13.756331 |
| `longitude` | float | GPS longitude in decimal degrees | 100.501765 |
| `radius` | int | Validation radius in meters | 200 |
| `location_name` | string | Human-readable location name | "Main Office Bangkok" |
| `office_type` | string | "main" or "branch" | "main" |
| `updated_at` | string | ISO 8601 timestamp | "2025-01-10T14:30:00Z" |

## GPS Validation Flow

When employee checks in via QR code:

1. **Mobile app requests GPS**
   - Browser geolocation API gets user coordinates
   - Accuracy must be ≤50m for validation

2. **Server validates location**
   - Extracts terminal GPS from device metadata
   - Calculates distance using Haversine formula
   - Compares distance vs configured radius

3. **Accept or Reject**
   - ✅ Within radius: Check-in allowed
   - ❌ Outside radius: Check-in rejected with distance info

**Location Service Code:**
```python
from app.services.location_service import location_service

validation = location_service.validate_gps_location(
    user_lat=13.756500,
    user_lon=100.501800,
    user_accuracy=30,
    terminal_id=2,
    db=db_session
)

if validation["valid"]:
    # Allow check-in
    print(f"Distance: {validation['distance']}m")
else:
    # Reject check-in
    print(f"Too far: {validation['distance']}m > {validation['allowed_radius']}m")
```

## API Endpoints

### Get All Devices (with GPS)

```http
GET /api/devices/
```

**Response:**
```json
{
  "devices": [
    {
      "id": 2,
      "name": "QR Terminal - Main Office",
      "device_type": "qr_terminal",
      "device_metadata": "{\"gps\": {...}}",
      "ip_address": "192.168.1.100",
      "is_active": true
    }
  ]
}
```

### Update Device GPS

```http
PUT /api/devices/{device_id}
Content-Type: application/json

{
  "device_metadata": "{\"gps\": {\"latitude\": 13.756, \"longitude\": 100.501, \"radius\": 200, \"location_name\": \"Main Office\", \"office_type\": \"main\"}}"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Device QR Terminal - Main Office updated successfully",
  "device": {
    "id": 2,
    "device_metadata": "{\"gps\": {...}}"
  }
}
```

### Validate GPS Location

```http
POST /qr-checkin/api/qr/validate-location
Content-Type: application/json

{
  "terminal_id": 2,
  "latitude": 13.756500,
  "longitude": 100.501800,
  "accuracy": 30
}
```

**Response (Valid):**
```json
{
  "valid": true,
  "distance": 45.2,
  "allowed_radius": 200,
  "terminal_location": {
    "latitude": 13.756331,
    "longitude": 100.501765,
    "location_name": "Main Office Bangkok"
  },
  "message": "อยู่ในพื้นที่ Main Office Bangkok (45.2m)"
}
```

**Response (Invalid):**
```json
{
  "valid": false,
  "distance": 350.7,
  "allowed_radius": 200,
  "message": "อยู่นอกพื้นที่ Main Office Bangkok (350.7m > 200m)"
}
```

## Configuration Examples

### Main Office (Bangkok)

```json
{
  "gps": {
    "latitude": 13.756331,
    "longitude": 100.501765,
    "radius": 200,
    "location_name": "สำนักงานใหญ่ กรุงเทพฯ",
    "office_type": "main"
  }
}
```

### Branch Office (Chiang Mai)

```json
{
  "gps": {
    "latitude": 18.788050,
    "longitude": 98.985280,
    "radius": 150,
    "location_name": "สาขาเชียงใหม่ - MAYA Mall",
    "office_type": "branch"
  }
}
```

### Branch Office (Phuket)

```json
{
  "gps": {
    "latitude": 7.882056,
    "longitude": 98.391928,
    "radius": 300,
    "location_name": "สาขาภูเก็ต - Central Patong",
    "office_type": "branch"
  }
}
```

## Troubleshooting

### Map Not Loading

**Symptoms:** Blank map area, gray tiles, or "Tile not found" errors

**Causes:**
1. No internet connection
2. OpenStreetMap tile servers temporarily unavailable
3. Firewall blocking tile requests
4. Browser blocking mixed content (HTTP on HTTPS site)

**Solutions:**
1. Check internet connectivity
2. Wait a few minutes and refresh (tile servers may be temporarily overloaded)
3. Check firewall/proxy settings allow requests to `tile.openstreetmap.org`
4. Ensure site uses HTTPS to avoid mixed content issues
5. Check browser console for JavaScript errors

### Tiles Loading Slowly

**Symptoms:** Map tiles appear slowly or incompletely

**Causes:**
1. Slow internet connection
2. OpenStreetMap CDN congestion
3. Too many concurrent map instances

**Solutions:**
1. Be patient - tiles are cached after first load
2. Refresh page to retry failed tiles
3. Close other browser tabs using maps

### GPS Validation Failing

**Symptoms:** Valid location rejected as outside radius

**Causes:**
1. GPS accuracy too low (>50m)
2. Incorrect terminal_id in request
3. Terminal has no GPS configured
4. Radius set too small

**Solutions:**
1. Ensure GPS accuracy ≤50m before validation
2. Verify terminal_id matches device database
3. Configure GPS via admin panel
4. Increase validation radius if needed

### Save Button Disabled

**Symptoms:** Cannot save GPS location

**Causes:**
1. No location selected on map
2. No terminal selected
3. Location name not filled

**Solutions:**
1. Click on map or search location first
2. Select terminal from sidebar
3. Enter descriptive location name

## Best Practices

### Radius Selection

| Location Type | Recommended Radius | Reason |
|--------------|-------------------|---------|
| Small Office | 50-100m | Single building, precise check-in |
| Office Complex | 100-200m | Multiple buildings, parking area |
| Shopping Mall | 200-300m | Large area, multiple floors |
| Open Campus | 300-500m | University, large campus |

### Office Type Usage

**Main Office:**
- Primary headquarters
- Main administrative office
- Use for central reporting and analytics

**Branch Office:**
- Satellite offices
- Regional centers
- Remote locations

### OpenStreetMap Fair Use

**Please Respect OSM Tile Servers:**
1. **Attribution Required** - Always keep © OpenStreetMap credit visible (already included)
2. **Reasonable Usage** - Don't generate excessive tile requests
3. **Caching** - Browser automatically caches tiles (don't disable)
4. **No Bulk Downloads** - Don't download entire regions
5. **Be a Good Citizen** - Consider donating to OpenStreetMap if you find it valuable

**Tile Usage Policy:**
- OpenStreetMap tile servers are free but run by volunteers
- Heavy usage should consider self-hosting tiles or using commercial providers
- For most single-location use cases, default tiles are perfectly fine

### Security Considerations

1. **GPS Accuracy:**
   - Enforce minimum accuracy (≤50m)
   - Prevent spoofed GPS coordinates
   - Log validation attempts

2. **Radius Limits:**
   - Don't set radius too large (prevents GPS spoofing)
   - Don't set radius too small (causes false negatives)
   - Consider building size and parking

3. **Data Privacy:**
   - GPS coordinates stored locally in your database
   - No data sent to third-party services (except OpenStreetMap tiles)
   - Full control over location data

## Migration from Manual Coordinates

If you have existing GPS coordinates in database:

```sql
-- Update device with GPS metadata
UPDATE devices
SET device_metadata = json_object(
  'gps', json_object(
    'latitude', 13.756331,
    'longitude', 100.501765,
    'radius', 200,
    'location_name', 'Main Office Bangkok',
    'office_type', 'main',
    'updated_at', datetime('now')
  )
)
WHERE id = 2 AND device_type = 'qr_terminal';
```

## Future Enhancements

Planned features:
- [ ] Multi-location validation (check multiple offices)
- [ ] Geofencing alerts for admins
- [ ] Historical location tracking
- [ ] Mobile app GPS accuracy improvement
- [ ] Offline GPS caching
- [ ] Export GPS locations to KML/GeoJSON

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review browser console for JavaScript errors
3. Check server logs for API errors
4. Verify internet connectivity and firewall settings
5. Test with different browsers (Chrome, Firefox, Safari)
6. Check OpenStreetMap tile server status at [status.openstreetmap.org](https://status.openstreetmap.org/)

## References

- [Leaflet Documentation](https://leafletjs.com/) - Official Leaflet JavaScript library docs
- [OpenStreetMap](https://www.openstreetmap.org/) - Free, editable map of the world
- [Leaflet Quick Start Guide](https://leafletjs.com/examples/quick-start/) - Getting started tutorial
- [Leaflet Marker Documentation](https://leafletjs.com/reference.html#marker) - Draggable markers API
- [Leaflet Circle Documentation](https://leafletjs.com/reference.html#circle) - Circle overlay API
- [Haversine Distance Formula](https://en.wikipedia.org/wiki/Haversine_formula) - GPS distance calculation
- [HTML5 Geolocation API](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation_API) - Browser GPS API
