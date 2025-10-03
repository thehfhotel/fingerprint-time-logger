/**
 * QR Terminal GPS Location Admin Panel
 * Uses Leaflet + OpenStreetMap (Free, No API Key Required)
 */

// ============================================================================
// State Management
// ============================================================================

let map = null;
let marker = null;
let radiusCircle = null;
let terminals = [];
let currentTerminal = null;

const state = {
    selectedLocation: null,
    selectedTerminal: null,
    officeType: 'main', // 'main' or 'branch'
    hasChanges: false
};

// ============================================================================
// Leaflet Map Initialization
// ============================================================================

function initMap() {
    console.log('[GPS Admin] Initializing Leaflet Map with OpenStreetMap...');

    // Default center: Bangkok, Thailand
    const bangkokCenter = [13.7563, 100.5018];

    // Initialize Leaflet map
    map = L.map('map').setView(bangkokCenter, 12);

    // Add OpenStreetMap tile layer (FREE - No API key required!)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
        minZoom: 3
    }).addTo(map);

    // Add click listener to set GPS location
    map.on('click', (e) => {
        setLocation(e.latlng.lat, e.latlng.lng);
    });

    // Load terminals after map is ready
    setTimeout(() => {
        loadTerminals();
    }, 500);

    console.log('[GPS Admin] Map initialized successfully');
}

// ============================================================================
// Location Management
// ============================================================================

function setLocation(lat, lng) {
    console.log(`[GPS Admin] Setting location: ${lat}, ${lng}`);

    state.selectedLocation = { lat, lng };
    state.hasChanges = true;

    // Update input fields
    document.getElementById('latitude').value = lat.toFixed(6);
    document.getElementById('longitude').value = lng.toFixed(6);

    // Update marker
    if (!marker) {
        marker = L.marker([lat, lng], {
            draggable: true,
            title: 'ตำแหน่ง Terminal'
        }).addTo(map);

        // Add drag listener
        marker.on('dragend', (e) => {
            const pos = e.target.getLatLng();
            setLocation(pos.lat, pos.lng);
        });

        // Add popup
        marker.bindPopup('📍 ตำแหน่ง QR Terminal').openPopup();
    } else {
        marker.setLatLng([lat, lng]);
        marker.openPopup();
    }

    // Update radius circle
    updateRadiusCircle();

    // Center map on marker
    map.setView([lat, lng], 16);

    // Enable save button
    document.getElementById('saveBtn').disabled = false;
}

function updateRadiusCircle() {
    const radius = parseInt(document.getElementById('radiusSlider').value);

    if (!state.selectedLocation) return;

    if (radiusCircle) {
        map.removeLayer(radiusCircle);
    }

    radiusCircle = L.circle([state.selectedLocation.lat, state.selectedLocation.lng], {
        radius: radius,  // meters
        color: '#667eea',
        fillColor: '#667eea',
        fillOpacity: 0.2,
        weight: 2
    }).addTo(map);
}

// ============================================================================
// Terminal Management
// ============================================================================

async function loadTerminals() {
    console.log('[GPS Admin] Loading terminals...');

    try {
        const response = await fetch('/api/devices/');
        if (!response.ok) throw new Error('Failed to load terminals');

        const data = await response.json();

        // Filter QR terminals
        terminals = data.devices.filter(d => d.device_type === 'qr_terminal');

        renderTerminalList();
    } catch (error) {
        console.error('[GPS Admin] Error loading terminals:', error);
        showStatus('ไม่สามารถโหลดข้อมูล Terminal ได้', 'error');
    }
}

function renderTerminalList() {
    const listContainer = document.getElementById('terminalList');

    if (terminals.length === 0) {
        listContainer.innerHTML = `
            <div style="text-align: center; padding: 20px; color: #666;">
                <p>ยังไม่มี QR Terminal</p>
                <p style="font-size: 0.9rem; margin-top: 5px;">คลิกปุ่ม "เพิ่ม QR Terminal" เพื่อเริ่มต้น</p>
            </div>
        `;
        return;
    }

    listContainer.innerHTML = terminals.map(terminal => {
        const metadata = parseMetadata(terminal.device_metadata);
        const gps = metadata.gps || {};
        const hasGPS = gps.latitude && gps.longitude;
        const officeType = gps.office_type || 'branch';

        return `
            <div class="terminal-card" data-terminal-id="${terminal.id}">
                <div class="terminal-header">
                    <div class="terminal-name">
                        ${officeType === 'main' ? '🏢' : '🏪'} ${terminal.name}
                    </div>
                    <div class="terminal-badge">
                        ${officeType === 'main' ? 'สำนักงานใหญ่' : 'สาขา'}
                    </div>
                </div>
                <div class="terminal-info">
                    ID: ${terminal.id} | IP: ${terminal.ip_address}
                </div>
                ${hasGPS ? `
                    <div class="terminal-location">
                        📍 ${gps.location_name || 'ไม่ระบุชื่อ'}
                    </div>
                    <div class="terminal-info">
                        GPS: ${gps.latitude.toFixed(4)}, ${gps.longitude.toFixed(4)}
                        | รัศมี: ${gps.radius}m
                    </div>
                ` : `
                    <div class="terminal-location" style="color: #dc3545;">
                        ⚠️ ยังไม่ได้ตั้งค่า GPS
                    </div>
                `}
            </div>
        `;
    }).join('');

    // Add click listeners
    document.querySelectorAll('.terminal-card').forEach(card => {
        card.addEventListener('click', () => {
            const terminalId = parseInt(card.dataset.terminalId);
            selectTerminal(terminalId);
        });
    });
}

function selectTerminal(terminalId) {
    console.log(`[GPS Admin] Selecting terminal ${terminalId}`);

    const terminal = terminals.find(t => t.id === terminalId);
    if (!terminal) return;

    currentTerminal = terminal;
    state.selectedTerminal = terminalId;

    // Update UI
    document.querySelectorAll('.terminal-card').forEach(card => {
        card.classList.remove('active');
    });
    document.querySelector(`[data-terminal-id="${terminalId}"]`).classList.add('active');

    // Load GPS data
    const metadata = parseMetadata(terminal.device_metadata);
    const gps = metadata.gps || {};

    if (gps.latitude && gps.longitude) {
        setLocation(gps.latitude, gps.longitude);
        document.getElementById('locationName').value = gps.location_name || '';
        document.getElementById('radiusSlider').value = gps.radius || 200;
        document.getElementById('radiusValue').textContent = `${gps.radius || 200}m`;

        // Set office type
        state.officeType = gps.office_type || 'branch';
        updateOfficeTypeUI();

        document.getElementById('deleteBtn').disabled = false;
    } else {
        // No GPS data - reset form
        resetForm();
    }

    state.hasChanges = false;
}

function updateOfficeTypeUI() {
    document.querySelectorAll('.office-type-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.type === state.officeType) {
            btn.classList.add('active');
        }
    });
}

function parseMetadata(metadataStr) {
    try {
        return JSON.parse(metadataStr || '{}');
    } catch (e) {
        return {};
    }
}

// ============================================================================
// Save & Update
// ============================================================================

async function saveLocation() {
    if (!currentTerminal || !state.selectedLocation) {
        showStatus('กรุณาเลือก Terminal และตำแหน่ง GPS', 'error');
        return;
    }

    const locationName = document.getElementById('locationName').value.trim();
    if (!locationName) {
        showStatus('กรุณากรอกชื่อสถานที่', 'error');
        return;
    }

    const radius = parseInt(document.getElementById('radiusSlider').value);

    // Prepare GPS metadata
    const metadata = parseMetadata(currentTerminal.device_metadata);
    metadata.gps = {
        latitude: state.selectedLocation.lat,
        longitude: state.selectedLocation.lng,
        radius: radius,
        location_name: locationName,
        office_type: state.officeType,
        updated_at: new Date().toISOString()
    };

    console.log('[GPS Admin] Saving GPS location:', metadata);

    try {
        const response = await fetch(`/api/devices/${currentTerminal.id}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                device_metadata: JSON.stringify(metadata)
            })
        });

        if (!response.ok) throw new Error('Failed to save GPS location');

        showStatus('✅ บันทึกตำแหน่ง GPS สำเร็จ', 'success');
        state.hasChanges = false;

        // Reload terminals
        await loadTerminals();

        // Re-select current terminal
        if (currentTerminal) {
            selectTerminal(currentTerminal.id);
        }

    } catch (error) {
        console.error('[GPS Admin] Error saving GPS location:', error);
        showStatus('❌ ไม่สามารถบันทึกตำแหน่ง GPS ได้', 'error');
    }
}

async function deleteLocation() {
    if (!currentTerminal) return;

    if (!confirm(`ต้องการลบตำแหน่ง GPS ของ ${currentTerminal.name} ใช่หรือไม่?`)) {
        return;
    }

    const metadata = parseMetadata(currentTerminal.device_metadata);
    delete metadata.gps;

    try {
        const response = await fetch(`/api/devices/${currentTerminal.id}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                device_metadata: JSON.stringify(metadata)
            })
        });

        if (!response.ok) throw new Error('Failed to delete GPS location');

        showStatus('✅ ลบตำแหน่ง GPS สำเร็จ', 'success');

        // Reset form
        resetForm();

        // Reload terminals
        await loadTerminals();

    } catch (error) {
        console.error('[GPS Admin] Error deleting GPS location:', error);
        showStatus('❌ ไม่สามารถลบตำแหน่ง GPS ได้', 'error');
    }
}

// ============================================================================
// UI Helpers
// ============================================================================

function resetForm() {
    document.getElementById('locationName').value = '';
    document.getElementById('latitude').value = '';
    document.getElementById('longitude').value = '';
    document.getElementById('radiusSlider').value = 200;
    document.getElementById('radiusValue').textContent = '200m';

    if (marker) {
        map.removeLayer(marker);
        marker = null;
    }

    if (radiusCircle) {
        map.removeLayer(radiusCircle);
        radiusCircle = null;
    }

    state.selectedLocation = null;
    state.hasChanges = false;

    document.getElementById('saveBtn').disabled = true;
    document.getElementById('deleteBtn').disabled = true;

    // Reset to Bangkok center
    map.setView([13.7563, 100.5018], 12);
}

function showStatus(message, type) {
    const statusEl = document.getElementById('statusMessage');
    statusEl.textContent = message;
    statusEl.className = `status-message ${type}`;
    statusEl.style.display = 'block';

    setTimeout(() => {
        statusEl.style.display = 'none';
    }, 5000);
}

// ============================================================================
// Event Listeners
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    // Initialize map
    initMap();

    // Radius slider
    const radiusSlider = document.getElementById('radiusSlider');
    const radiusValue = document.getElementById('radiusValue');

    radiusSlider.addEventListener('input', () => {
        radiusValue.textContent = `${radiusSlider.value}m`;
        updateRadiusCircle();
        state.hasChanges = true;
    });

    // Office type selector
    document.querySelectorAll('.office-type-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            state.officeType = btn.dataset.type;
            updateOfficeTypeUI();
            state.hasChanges = true;
        });
    });

    // Action buttons
    document.getElementById('saveBtn').addEventListener('click', saveLocation);
    document.getElementById('resetBtn').addEventListener('click', resetForm);
    document.getElementById('deleteBtn').addEventListener('click', deleteLocation);

    // Add terminal button
    document.getElementById('addTerminalBtn').addEventListener('click', () => {
        alert('กรุณาเพิ่ม QR Terminal ผ่านหน้า Device Management ก่อน จากนั้นจึงมาตั้งค่า GPS ที่นี่');
    });

    // Location name change
    document.getElementById('locationName').addEventListener('input', () => {
        state.hasChanges = true;
    });

    // Warn before leaving if unsaved changes
    window.addEventListener('beforeunload', (e) => {
        if (state.hasChanges) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
});

// ============================================================================
// Export for debugging
// ============================================================================

window.gpsAdmin = {
    state,
    map,
    terminals,
    loadTerminals,
    saveLocation,
    version: 'Leaflet + OpenStreetMap (Free)'
};

console.log('[GPS Admin] Leaflet + OpenStreetMap loaded successfully - No API key required!');
