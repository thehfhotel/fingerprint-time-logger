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
        const response = await fetch('/fingerprintlogs/api/devices/');
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

        return `
            <div class="terminal-card" data-terminal-id="${terminal.id}">
                <div class="terminal-header">
                    <div class="terminal-name">
                        📍 ${terminal.name}
                    </div>
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

    // Load terminal name
    document.getElementById('terminalName').value = terminal.name;
    document.getElementById('updateNameBtn').disabled = false;

    // Load GPS data
    const metadata = parseMetadata(terminal.device_metadata);
    const gps = metadata.gps || {};

    if (gps.latitude && gps.longitude) {
        setLocation(gps.latitude, gps.longitude);
        document.getElementById('locationName').value = gps.location_name || '';
        document.getElementById('radiusSlider').value = gps.radius || 200;
        document.getElementById('radiusValue').textContent = `${gps.radius || 200}m`;

        document.getElementById('deleteBtn').disabled = false;
    } else {
        // No GPS data - reset form
        resetForm();
    }

    // Enable delete terminal button when a terminal is selected
    document.getElementById('deleteTerminalBtn').disabled = false;

    state.hasChanges = false;
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
        updated_at: new Date().toISOString()
    };

    console.log('[GPS Admin] Saving GPS location:', metadata);

    try {
        const response = await fetch(`/fingerprintlogs/api/devices/${currentTerminal.id}`, {
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

    // Store terminal ID for re-selection after reload
    const terminalId = currentTerminal.id;

    const metadata = parseMetadata(currentTerminal.device_metadata);
    delete metadata.gps;

    try {
        const response = await fetch(`/fingerprintlogs/api/devices/${terminalId}`, {
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

        // Reload terminals to reflect changes
        await loadTerminals();

        // Re-select terminal to update UI state properly
        // This will show the terminal without GPS and disable the delete button
        selectTerminal(terminalId);

    } catch (error) {
        console.error('[GPS Admin] Error deleting GPS location:', error);
        showStatus('❌ ไม่สามารถลบตำแหน่ง GPS ได้', 'error');
    }
}

async function updateTerminalName() {
    if (!currentTerminal) return;

    const newName = document.getElementById('terminalName').value.trim();

    // Validation
    if (!newName) {
        showStatus('กรุณากรอกชื่อ Terminal', 'error');
        return;
    }

    if (newName === currentTerminal.name) {
        showStatus('ชื่อ Terminal ไม่เปลี่ยนแปลง', 'error');
        return;
    }

    console.log(`[GPS Admin] Updating terminal ${currentTerminal.id} name: ${currentTerminal.name} → ${newName}`);

    try {
        const response = await fetch(`/fingerprintlogs/api/devices/${currentTerminal.id}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: newName
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Failed to update terminal name');
        }

        const result = await response.json();
        console.log('[GPS Admin] Terminal name updated:', result);

        showStatus('✅ อัปเดตชื่อ Terminal สำเร็จ', 'success');

        // Reload terminals to reflect changes in sidebar
        await loadTerminals();

        // Re-select current terminal to refresh UI
        if (currentTerminal) {
            selectTerminal(currentTerminal.id);
        }

    } catch (error) {
        console.error('[GPS Admin] Error updating terminal name:', error);
        showStatus(`❌ ไม่สามารถอัปเดตชื่อ Terminal ได้: ${error.message}`, 'error');
    }
}

async function deleteTerminal() {
    if (!currentTerminal) return;

    if (!confirm(`⚠️ คำเตือน: ต้องการลบ QR Terminal "${currentTerminal.name}" ออกจากระบบใช่หรือไม่?\n\nการดำเนินการนี้จะลบ Terminal และข้อมูล GPS ทั้งหมด`)) {
        return;
    }

    const terminalId = currentTerminal.id;
    const terminalName = currentTerminal.name;

    console.log(`[GPS Admin] Deleting terminal ${terminalId}: ${terminalName}`);

    try {
        const response = await fetch(`/fingerprintlogs/api/devices/${terminalId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Failed to delete terminal');
        }

        showStatus(`✅ ลบ Terminal "${terminalName}" สำเร็จ`, 'success');

        // Clear current terminal and reset form
        currentTerminal = null;
        state.selectedTerminal = null;
        resetForm();

        // Reload terminals to reflect changes
        await loadTerminals();

    } catch (error) {
        console.error('[GPS Admin] Error deleting terminal:', error);
        showStatus(`❌ ไม่สามารถลบ Terminal ได้: ${error.message}`, 'error');
    }
}

// ============================================================================
// UI Helpers
// ============================================================================

function resetForm() {
    document.getElementById('terminalName').value = '';
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

    document.getElementById('updateNameBtn').disabled = true;
    document.getElementById('saveBtn').disabled = true;
    document.getElementById('deleteBtn').disabled = true;
    document.getElementById('deleteTerminalBtn').disabled = true;

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

    // Action buttons
    document.getElementById('updateNameBtn').addEventListener('click', updateTerminalName);
    document.getElementById('saveBtn').addEventListener('click', saveLocation);
    document.getElementById('deleteBtn').addEventListener('click', deleteLocation);
    document.getElementById('deleteTerminalBtn').addEventListener('click', deleteTerminal);

    // Add terminal button
    document.getElementById('addTerminalBtn').addEventListener('click', openAddTerminalModal);

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
// Add Terminal Modal Functions
// ============================================================================

function openAddTerminalModal() {
    const modal = document.getElementById('addTerminalModal');
    modal.classList.add('show');

    // Reset form
    document.getElementById('newTerminalName').value = '';

    // Focus on input after modal animation
    setTimeout(() => {
        document.getElementById('newTerminalName').focus();
    }, 300);
}

function closeAddTerminalModal() {
    const modal = document.getElementById('addTerminalModal');
    modal.classList.remove('show');
}

async function saveNewTerminal() {
    const terminalName = document.getElementById('newTerminalName').value.trim();

    // Validation
    if (!terminalName) {
        alert('กรุณากรอกชื่อ Terminal');
        return;
    }

    console.log('[GPS Admin] Creating new terminal:', {
        name: terminalName,
        device_type: 'qr_terminal'
    });

    try {
        const response = await fetch('/fingerprintlogs/api/devices/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: terminalName,
                device_type: 'qr_terminal',
                ip_address: null,  // QR terminals don't use IP
                port: null,        // QR terminals don't use port
                is_active: true,
                device_metadata: null  // GPS will be configured later via admin page
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Failed to create terminal');
        }

        const result = await response.json();
        console.log('[GPS Admin] Terminal created:', result);

        showStatus('✅ เพิ่ม Terminal สำเร็จ - คลิกเพื่อตั้งค่า GPS', 'success');
        closeAddTerminalModal();

        // Reload terminals
        await loadTerminals();

        // Auto-select the newly created terminal
        if (result.device && result.device.id) {
            setTimeout(() => {
                selectTerminal(result.device.id);
            }, 500);
        }
    } catch (error) {
        console.error('[GPS Admin] Error creating terminal:', error);
        showStatus(`❌ ไม่สามารถเพิ่ม Terminal ได้: ${error.message}`, 'error');
    }
}

// ============================================================================
// Export for debugging
// ============================================================================

window.gpsAdmin = {
    state,
    map,
    terminals,
    loadTerminals,
    saveLocation,
    openAddTerminalModal,
    closeAddTerminalModal,
    saveNewTerminal,
    version: 'Leaflet + OpenStreetMap (Free)'
};

console.log('[GPS Admin] Leaflet + OpenStreetMap loaded successfully - No API key required!');
