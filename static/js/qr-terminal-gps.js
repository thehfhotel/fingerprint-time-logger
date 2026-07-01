/**
 * QR Terminal GPS Configuration Modal
 * Inline GPS configuration with admin authentication
 * Uses Leaflet + OpenStreetMap (Free, No API Key Required)
 */

// ============================================================================
// State Management
// ============================================================================

let gpsMap = null;
let gpsMarker = null;
let gpsRadiusCircle = null;
let currentGPSData = null;

const gpsState = {
    authenticated: false,
    selectedLocation: null,
    officeType: 'main',
    hasChanges: false
};

// ============================================================================
// LocalStorage Cache Management
// ============================================================================

const GPS_CACHE_KEY = `qr_terminal_gps_${TERMINAL_ID}`;
const GPS_CACHE_VERSION = '1.0';

function cacheGPSData(gpsData) {
    try {
        const cacheData = {
            version: GPS_CACHE_VERSION,
            terminal_id: TERMINAL_ID,
            gps: gpsData,
            cached_at: new Date().toISOString()
        };
        localStorage.setItem(GPS_CACHE_KEY, JSON.stringify(cacheData));
        console.log('[GPS Cache] GPS data cached to localStorage:', gpsData);
    } catch (error) {
        console.error('[GPS Cache] Failed to cache GPS data:', error);
    }
}

function getCachedGPSData() {
    try {
        const cached = localStorage.getItem(GPS_CACHE_KEY);
        if (!cached) return null;

        const cacheData = JSON.parse(cached);

        // Validate cache structure
        if (!cacheData.gps || cacheData.terminal_id !== TERMINAL_ID) {
            console.warn('[GPS Cache] Invalid cache data, clearing...');
            clearGPSCache();
            return null;
        }

        console.log('[GPS Cache] GPS data loaded from localStorage:', cacheData.gps);
        return cacheData.gps;
    } catch (error) {
        console.error('[GPS Cache] Failed to read cached GPS data:', error);
        clearGPSCache();
        return null;
    }
}

function clearGPSCache() {
    try {
        localStorage.removeItem(GPS_CACHE_KEY);
        console.log('[GPS Cache] GPS cache cleared');
    } catch (error) {
        console.error('[GPS Cache] Failed to clear GPS cache:', error);
    }
}

// ============================================================================
// Modal Management
// ============================================================================

function openGPSModal() {
    console.log('[GPS Modal] Opening GPS configuration modal');
    const modal = document.getElementById('gpsModal');
    modal.style.display = 'flex';

    // Reset to auth step
    resetGPSModal();
}

function closeGPSModal() {
    console.log('[GPS Modal] Closing GPS configuration modal');
    const modal = document.getElementById('gpsModal');
    modal.style.display = 'none';

    // Clean up map
    if (gpsMap) {
        gpsMap.remove();
        gpsMap = null;
        gpsMarker = null;
        gpsRadiusCircle = null;
    }

    gpsState.authenticated = false;
    gpsState.hasChanges = false;
}

function resetGPSModal() {
    // Show auth step, hide config step
    document.getElementById('gpsAuthStep').style.display = 'block';
    document.getElementById('gpsConfigStep').style.display = 'none';

    // Clear password field
    document.getElementById('gpsAdminPassword').value = '';
    document.getElementById('gpsAuthError').style.display = 'none';

    gpsState.authenticated = false;
}

// ============================================================================
// Authentication
// ============================================================================

function verifyAdminPassword() {
    const inputPassword = document.getElementById('gpsAdminPassword').value;
    const errorDiv = document.getElementById('gpsAuthError');

    if (inputPassword === ADMIN_PASSWORD) {
        console.log('[GPS Modal] Admin authentication successful');
        gpsState.authenticated = true;
        errorDiv.style.display = 'none';

        // Switch to config step
        document.getElementById('gpsAuthStep').style.display = 'none';
        document.getElementById('gpsConfigStep').style.display = 'block';

        // Initialize map and load GPS data
        setTimeout(() => {
            initGPSMap();
            loadTerminalGPSData();
        }, 100);

    } else {
        console.log('[GPS Modal] Admin authentication failed');
        errorDiv.textContent = '❌ รหัสผ่านไม่ถูกต้อง';
        errorDiv.style.display = 'block';
    }
}

// ============================================================================
// Leaflet Map Initialization
// ============================================================================

function initGPSMap() {
    if (gpsMap) {
        console.log('[GPS Modal] Map already initialized');
        return;
    }

    console.log('[GPS Modal] Initializing Leaflet Map');

    // Default center: Bangkok, Thailand
    const bangkokCenter = [13.7563, 100.5018];

    // Initialize Leaflet map
    gpsMap = L.map('gpsMap').setView(bangkokCenter, 12);

    // Add OpenStreetMap tile layer (FREE - No API key required!)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
        minZoom: 3
    }).addTo(gpsMap);

    // Add click listener to set GPS location
    gpsMap.on('click', (e) => {
        setGPSLocation(e.latlng.lat, e.latlng.lng);
    });

    console.log('[GPS Modal] Map initialized successfully');
}

// ============================================================================
// GPS Location Management
// ============================================================================

function setGPSLocation(lat, lng) {
    console.log(`[GPS Modal] Setting location: ${lat}, ${lng}`);

    gpsState.selectedLocation = { lat, lng };
    gpsState.hasChanges = true;

    // Update input fields
    document.getElementById('gpsLatitude').value = lat.toFixed(6);
    document.getElementById('gpsLongitude').value = lng.toFixed(6);

    // Update marker
    if (!gpsMarker) {
        gpsMarker = L.marker([lat, lng], {
            draggable: true,
            title: `ตำแหน่ง Terminal ${TERMINAL_ID}`
        }).addTo(gpsMap);

        // Add drag listener
        gpsMarker.on('dragend', (e) => {
            const pos = e.target.getLatLng();
            setGPSLocation(pos.lat, pos.lng);
        });

        // Add popup
        gpsMarker.bindPopup(`📍 QR Terminal ${TERMINAL_ID}`).openPopup();
    } else {
        gpsMarker.setLatLng([lat, lng]);
        gpsMarker.openPopup();
    }

    // Update radius circle
    updateGPSRadiusCircle();

    // Center map on marker
    gpsMap.setView([lat, lng], 16);

    // Enable save button
    document.getElementById('gpsSaveBtn').disabled = false;
}

function updateGPSRadiusCircle() {
    const radius = parseInt(document.getElementById('gpsRadiusSlider').value);

    if (!gpsState.selectedLocation) return;

    if (gpsRadiusCircle) {
        gpsMap.removeLayer(gpsRadiusCircle);
    }

    gpsRadiusCircle = L.circle(
        [gpsState.selectedLocation.lat, gpsState.selectedLocation.lng],
        {
            radius: radius,  // meters
            color: '#2F855A',
            fillColor: '#2F855A',
            fillOpacity: 0.2,
            weight: 2
        }
    ).addTo(gpsMap);
}

// ============================================================================
// Load Terminal GPS Data
// ============================================================================

function loadGPSDataToForm(gps) {
    if (!gps || !gps.latitude || !gps.longitude) return;

    console.log('[GPS Form] Loading GPS data to form:', gps);

    // Set location
    setGPSLocation(gps.latitude, gps.longitude);

    // Set location name
    document.getElementById('gpsLocationName').value = gps.location_name || '';

    // Set radius
    const radius = gps.radius || 200;
    document.getElementById('gpsRadiusSlider').value = radius;
    document.getElementById('gpsRadiusValue').textContent = radius;

    // Set office type
    gpsState.officeType = gps.office_type || 'main';
    updateOfficeTypeUI();

    // Enable delete button
    document.getElementById('gpsDeleteBtn').disabled = false;

    gpsState.hasChanges = false;
}

async function loadTerminalGPSData() {
    console.log(`[GPS Modal] Loading GPS data for terminal ${TERMINAL_ID}`);

    try {
        const response = await fetch('/api/private/devices/');
        if (!response.ok) throw new Error('Failed to load devices');

        const data = await response.json();

        // Find current terminal
        const terminal = data.devices.find(d => d.id === parseInt(TERMINAL_ID));

        if (!terminal) {
            console.warn(`[GPS Modal] Terminal ${TERMINAL_ID} not found`);
            // Try to use cached data as fallback
            const cachedGPS = getCachedGPSData();
            if (cachedGPS) {
                console.log('[GPS Modal] Using cached GPS data as fallback');
                loadGPSDataToForm(cachedGPS);
                currentGPSData = cachedGPS;
            } else {
                showGPSStatus('⚠️ ไม่พบข้อมูล Terminal', 'warning');
            }
            return;
        }

        // Parse GPS metadata
        let metadata = {};
        try {
            metadata = JSON.parse(terminal.device_metadata || '{}');
        } catch (e) {
            console.warn('[GPS Modal] Failed to parse metadata:', e);
        }

        const gps = metadata.gps || {};
        currentGPSData = gps;

        if (gps.latitude && gps.longitude) {
            console.log('[GPS Modal] Existing GPS data found:', gps);
            loadGPSDataToForm(gps);
            // Cache GPS data to localStorage
            cacheGPSData(gps);
        } else {
            console.log('[GPS Modal] No GPS data configured yet');
            showGPSStatus('ℹ️ ยังไม่มีข้อมูล GPS กรุณาคลิกบนแผนที่เพื่อตั้งค่า', 'info');
        }

    } catch (error) {
        console.error('[GPS Modal] Error loading GPS data:', error);
        showGPSStatus('❌ ไม่สามารถโหลดข้อมูล GPS ได้', 'error');
    }
}

// ============================================================================
// Save GPS Configuration
// ============================================================================

async function saveGPSConfiguration() {
    if (!gpsState.selectedLocation) {
        showGPSStatus('⚠️ กรุณาเลือกตำแหน่ง GPS บนแผนที่', 'warning');
        return;
    }

    const locationName = document.getElementById('gpsLocationName').value.trim();
    if (!locationName) {
        showGPSStatus('⚠️ กรุณากรอกชื่อสถานที่', 'warning');
        return;
    }

    const radius = parseInt(document.getElementById('gpsRadiusSlider').value);

    // Prepare GPS metadata
    const gpsData = {
        latitude: gpsState.selectedLocation.lat,
        longitude: gpsState.selectedLocation.lng,
        radius: radius,
        location_name: locationName,
        office_type: gpsState.officeType,
        updated_at: new Date().toISOString()
    };

    console.log('[GPS Modal] Saving GPS configuration:', gpsData);

    try {
        // Get current device metadata
        const getResponse = await fetch('/fingerprintlogs/api/devices/');
        if (!getResponse.ok) throw new Error('Failed to load devices');

        const deviceData = await getResponse.json();
        const terminal = deviceData.devices.find(d => d.id === parseInt(TERMINAL_ID));

        if (!terminal) {
            throw new Error(`Terminal ${TERMINAL_ID} not found`);
        }

        // Parse existing metadata
        let metadata = {};
        try {
            metadata = JSON.parse(terminal.device_metadata || '{}');
        } catch (e) {
            metadata = {};
        }

        // Update GPS data
        metadata.gps = gpsData;

        // Save to server
        const saveResponse = await fetch(`/api/private/devices/${TERMINAL_ID}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                device_metadata: JSON.stringify(metadata)
            })
        });

        if (!saveResponse.ok) {
            const errorData = await saveResponse.json();
            throw new Error(errorData.detail || 'Failed to save GPS configuration');
        }

        console.log('[GPS Modal] GPS configuration saved successfully');
        showGPSStatus('✅ บันทึกตำแหน่ง GPS สำเร็จ', 'success');

        gpsState.hasChanges = false;
        currentGPSData = gpsData;

        // Enable delete button
        document.getElementById('gpsDeleteBtn').disabled = false;

        // Cache GPS data to localStorage
        cacheGPSData(gpsData);

        // Update footer if exists
        updateTerminalFooter(gpsData);

    } catch (error) {
        console.error('[GPS Modal] Error saving GPS configuration:', error);
        showGPSStatus(`❌ ไม่สามารถบันทึกได้: ${error.message}`, 'error');
    }
}

// ============================================================================
// Delete GPS Configuration
// ============================================================================

async function deleteGPSConfiguration() {
    if (!confirm(`ต้องการลบตำแหน่ง GPS ของ Terminal ${TERMINAL_ID} ใช่หรือไม่?`)) {
        return;
    }

    console.log('[GPS Modal] Deleting GPS configuration');

    try {
        // Get current device metadata
        const getResponse = await fetch('/fingerprintlogs/api/devices/');
        if (!getResponse.ok) throw new Error('Failed to load devices');

        const deviceData = await getResponse.json();
        const terminal = deviceData.devices.find(d => d.id === parseInt(TERMINAL_ID));

        if (!terminal) {
            throw new Error(`Terminal ${TERMINAL_ID} not found`);
        }

        // Parse existing metadata
        let metadata = {};
        try {
            metadata = JSON.parse(terminal.device_metadata || '{}');
        } catch (e) {
            metadata = {};
        }

        // Remove GPS data
        delete metadata.gps;

        // Save to server
        const saveResponse = await fetch(`/api/private/devices/${TERMINAL_ID}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                device_metadata: JSON.stringify(metadata)
            })
        });

        if (!saveResponse.ok) {
            const errorData = await saveResponse.json();
            throw new Error(errorData.detail || 'Failed to delete GPS configuration');
        }

        console.log('[GPS Modal] GPS configuration deleted successfully');
        showGPSStatus('✅ ลบตำแหน่ง GPS สำเร็จ', 'success');

        // Clear localStorage cache
        clearGPSCache();

        // Reset form
        resetGPSForm();

        // Update footer
        updateTerminalFooter(null);

    } catch (error) {
        console.error('[GPS Modal] Error deleting GPS configuration:', error);
        showGPSStatus(`❌ ไม่สามารถลบได้: ${error.message}`, 'error');
    }
}

// ============================================================================
// UI Helpers
// ============================================================================

function resetGPSForm() {
    document.getElementById('gpsLocationName').value = '';
    document.getElementById('gpsLatitude').value = '';
    document.getElementById('gpsLongitude').value = '';
    document.getElementById('gpsRadiusSlider').value = 200;
    document.getElementById('gpsRadiusValue').textContent = '200';

    if (gpsMarker) {
        gpsMap.removeLayer(gpsMarker);
        gpsMarker = null;
    }

    if (gpsRadiusCircle) {
        gpsMap.removeLayer(gpsRadiusCircle);
        gpsRadiusCircle = null;
    }

    gpsState.selectedLocation = null;
    gpsState.hasChanges = false;
    currentGPSData = null;

    document.getElementById('gpsSaveBtn').disabled = true;
    document.getElementById('gpsDeleteBtn').disabled = true;

    // Reset to Bangkok center
    if (gpsMap) {
        gpsMap.setView([13.7563, 100.5018], 12);
    }
}

function updateOfficeTypeUI() {
    document.querySelectorAll('.gps-office-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.type === gpsState.officeType) {
            btn.classList.add('active');
        }
    });
}

function showGPSStatus(message, type) {
    const statusEl = document.getElementById('gpsStatusMessage');
    statusEl.textContent = message;
    statusEl.className = `gps-status-message ${type}`;
    statusEl.style.display = 'block';

    setTimeout(() => {
        statusEl.style.display = 'none';
    }, 5000);
}

function updateTerminalFooter(gpsData) {
    // Update footer GPS display if it exists
    const footerGPS = document.getElementById('footerGPS');
    const footerLocation = document.getElementById('footerLocation');

    if (footerGPS && gpsData) {
        footerGPS.textContent = `${gpsData.latitude.toFixed(4)}, ${gpsData.longitude.toFixed(4)}`;
    } else if (footerGPS) {
        footerGPS.textContent = '-';
    }

    if (footerLocation && gpsData) {
        footerLocation.textContent = gpsData.location_name;
    } else if (footerLocation) {
        footerLocation.textContent = '-';
    }
}

// ============================================================================
// Initialize GPS Data from Cache
// ============================================================================

function initializeGPSFromCache() {
    console.log('[GPS Init] Attempting to restore GPS data from cache');

    const cachedGPS = getCachedGPSData();
    if (cachedGPS && cachedGPS.latitude && cachedGPS.longitude) {
        console.log('[GPS Init] Cached GPS data found, updating footer');
        currentGPSData = cachedGPS;

        // Update footer display immediately
        updateTerminalFooter(cachedGPS);

        return true;
    } else {
        console.log('[GPS Init] No cached GPS data available');
        return false;
    }
}

// ============================================================================
// Event Listeners
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    console.log('[GPS Modal] Initializing GPS configuration module');

    // Restore GPS data from cache on page load
    initializeGPSFromCache();

    // GPS config button
    const gpsConfigButton = document.getElementById('gpsConfigButton');
    if (gpsConfigButton) {
        gpsConfigButton.addEventListener('click', openGPSModal);
    }

    // Close buttons
    const closeButtons = document.querySelectorAll('.gps-close-btn');
    closeButtons.forEach(btn => {
        btn.addEventListener('click', closeGPSModal);
    });

    // Close on outside click
    const modal = document.getElementById('gpsModal');
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeGPSModal();
            }
        });
    }

    // Admin password submit
    const authSubmit = document.getElementById('gpsAuthSubmit');
    if (authSubmit) {
        authSubmit.addEventListener('click', verifyAdminPassword);
    }

    // Enter key on password field
    const passwordInput = document.getElementById('gpsAdminPassword');
    if (passwordInput) {
        passwordInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                verifyAdminPassword();
            }
        });
    }

    // Office type buttons
    document.querySelectorAll('.gps-office-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            gpsState.officeType = btn.dataset.type;
            updateOfficeTypeUI();
            gpsState.hasChanges = true;
        });
    });

    // Radius slider
    const radiusSlider = document.getElementById('gpsRadiusSlider');
    const radiusValue = document.getElementById('gpsRadiusValue');
    if (radiusSlider && radiusValue) {
        radiusSlider.addEventListener('input', () => {
            radiusValue.textContent = radiusSlider.value;
            updateGPSRadiusCircle();
            gpsState.hasChanges = true;
        });
    }

    // Location name input
    const locationNameInput = document.getElementById('gpsLocationName');
    if (locationNameInput) {
        locationNameInput.addEventListener('input', () => {
            gpsState.hasChanges = true;
        });
    }

    // Action buttons
    const saveBtn = document.getElementById('gpsSaveBtn');
    if (saveBtn) {
        saveBtn.addEventListener('click', saveGPSConfiguration);
    }

    const resetBtn = document.getElementById('gpsResetBtn');
    if (resetBtn) {
        resetBtn.addEventListener('click', resetGPSForm);
    }

    const deleteBtn = document.getElementById('gpsDeleteBtn');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', deleteGPSConfiguration);
    }

    // Warn before leaving if unsaved changes
    window.addEventListener('beforeunload', (e) => {
        if (gpsState.hasChanges && gpsState.authenticated) {
            e.preventDefault();
            e.returnValue = '';
        }
    });

    console.log('[GPS Modal] GPS configuration module ready');
});

// ============================================================================
// Export for debugging
// ============================================================================

window.gpsModal = {
    state: gpsState,
    map: () => gpsMap,
    openModal: openGPSModal,
    closeModal: closeGPSModal,
    version: 'Leaflet + OpenStreetMap (Free)'
};

console.log('[GPS Modal] GPS configuration module loaded - No API key required!');
