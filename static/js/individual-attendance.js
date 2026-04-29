// Individual Attendance Page JavaScript - Cache Bust v2.9-timezone-fix-' + Date.now()
console.log('🚀 Individual Attendance JS Loaded - Version:', '2.9-timezone-fix-' + Date.now());

/**
 * Escape HTML-special characters to prevent stored XSS via innerHTML.
 * Use anywhere server-supplied strings are interpolated into HTML.
 */
function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function(c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

class IndividualAttendanceManager {
    constructor() {
        this.selectedEmployeeId = null;
        this.employees = [];
        this.attendanceData = [];
        this.initializeEventListeners();
        this.setDefaultDates();
        // loadEmployees() will be called after initialization
    }

    async initialize() {
        await this.loadEmployees();
    }

    initializeEventListeners() {
        // Search functionality
        const searchInput = document.getElementById('nicknameSearch');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => this.filterEmployees(e.target.value));
        }

        // Filter button
        const filterButton = document.getElementById('filterButton');
        if (filterButton) {
            filterButton.addEventListener('click', () => this.loadAttendanceData());
        }

        // Enter key on date inputs
        document.getElementById('startDate')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.loadAttendanceData();
        });
        document.getElementById('endDate')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.loadAttendanceData();
        });
    }

    setDefaultDates() {
        const today = new Date();
        const thirtyDaysAgo = new Date(today);
        thirtyDaysAgo.setDate(today.getDate() - 30);

        document.getElementById('endDate').value = today.toISOString().split('T')[0];
        document.getElementById('startDate').value = thirtyDaysAgo.toISOString().split('T')[0];
    }

    async loadEmployees() {
        try {
            // Use same parameters as nickname-management page for consistent data
            const params = new URLSearchParams({
                from_device: 'true',        // Always fetch from ZK device
                include_hidden: 'false',    // Don't show hidden employees in attendance view
                include_inactive: 'true'    // Show inactive employees (they might have attendance records)
            });

            const apiUrl = appConfig.getApiUrl(`employees/?${params}`);
            console.log('🔍 Loading employees from:', apiUrl);
            console.log('🔗 URL passed to fetch():', apiUrl);
            console.log('📊 URL protocol check:', apiUrl.startsWith('https://') ? 'HTTPS ✅' : 'HTTP ❌');

            const response = await fetch(apiUrl);
            if (!response.ok) throw new Error(`Failed to load employees: ${response.status} ${response.statusText}`);

            const data = await response.json();
            this.employees = data.employees || [];
            this.renderEmployeeList();
            console.log('Employees loaded successfully:', this.employees.length, 'employees');
        } catch (error) {
            console.error('Error loading employees:', error);
            console.error('API URL that failed:', appConfig.getApiUrl('employees'));
            document.getElementById('nicknameList').innerHTML =
                '<div class="loading">ไม่สามารถโหลดรายชื่อพนักงานได้</div>';
        }
    }

    renderEmployeeList(filteredEmployees = null) {
        const listContainer = document.getElementById('nicknameList');
        const employeesToRender = filteredEmployees || this.employees;

        if (employeesToRender.length === 0) {
            listContainer.innerHTML = '<div class="loading">ไม่พบพนักงาน</div>';
            return;
        }

        listContainer.innerHTML = employeesToRender
            .sort((a, b) => {
                // Sort by display_name (matches nickname-management page)
                const nameA = (a.display_name || a.badge_number || '').toLowerCase();
                const nameB = (b.display_name || b.badge_number || '').toLowerCase();
                return nameA.localeCompare(nameB);
            })
            .map(employee => {
                const displayName = employee.display_name || `Employee #${employee.badge_number}` || 'No Name';
                const activeClass = employee.badge_number === this.selectedEmployeeId ? 'active' : '';
                const safeDisplayName = escapeHtml(displayName);
                const safeBadge = escapeHtml(employee.badge_number);
                // Two layers: first JS-escape for the string literal, then HTML-escape
                // because the result is interpolated into a double-quoted attribute.
                const jsEscapedName = String(displayName).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                const jsEscapedBadge = String(employee.badge_number).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                const onclickAttr = escapeHtml(
                    `attendanceManager.selectEmployee('${jsEscapedBadge}', '${jsEscapedName}')`
                );
                return `
                    <div class="nickname-item ${activeClass}"
                         data-employee-id="${safeBadge}"
                         data-employee-name="${safeDisplayName}"
                         onclick="${onclickAttr}">
                        <span>${safeDisplayName}</span>
                        <span class="badge-id">#${safeBadge}</span>
                    </div>
                `;
            }).join('');
    }

    filterEmployees(searchTerm) {
        if (!searchTerm) {
            this.renderEmployeeList();
            return;
        }

        const term = searchTerm.toLowerCase();
        const filtered = this.employees.filter(employee => {
            const displayName = (employee.display_name || '').toLowerCase();
            const badge = (employee.badge_number || '').toString();

            return displayName.includes(term) ||
                   badge.includes(term);
        });

        this.renderEmployeeList(filtered);
    }

    selectEmployee(employeeId, employeeName) {
        // Update selection state
        this.selectedEmployeeId = employeeId;

        // Update UI
        document.getElementById('selectedEmployeeName').textContent = employeeName;

        // Update active state in list
        document.querySelectorAll('.nickname-item').forEach(item => {
            item.classList.remove('active');
        });
        document.querySelector(`[data-employee-id="${employeeId}"]`)?.classList.add('active');

        // Load attendance data
        this.loadAttendanceData();
    }

    async loadAttendanceData() {
        if (!this.selectedEmployeeId) {
            this.showNoDataMessage('เลือกพนักงานเพื่อดูข้อมูลการเข้า-ออกงาน');
            return;
        }

        const startDate = document.getElementById('startDate').value;
        const endDate = document.getElementById('endDate').value;

        if (!startDate || !endDate) {
            this.showNoDataMessage('กรุณาเลือกช่วงวันที่');
            return;
        }

        this.showLoading(true);

        try {
            const response = await fetch(
                appConfig.getApiUrl(`attendance/employee/badge/${this.selectedEmployeeId}?start_date=${startDate}&end_date=${endDate}`)
            );

            if (!response.ok) throw new Error('Failed to load attendance data');

            const data = await response.json();
            this.attendanceData = data.records || [];
            this.renderAttendanceTable();
        } catch (error) {
            console.error('Error loading attendance data:', error);
            this.showNoDataMessage('ไม่สามารถโหลดข้อมูลการเข้า-ออกงานได้');
        } finally {
            this.showLoading(false);
        }
    }

    renderAttendanceTable() {
        const tableBody = document.getElementById('attendanceTableBody');

        if (this.attendanceData.length === 0) {
            this.showNoDataMessage('ไม่พบข้อมูลการเข้า-ออกงานในช่วงเวลาที่เลือก');
            return;
        }

        // Group attendance records by date (Bangkok timezone)
        const groupedData = {};
        this.attendanceData.forEach(record => {
            if (record.timestamp) {
                // Convert UTC timestamp to Bangkok date
                const bangkokDate = new Date(record.timestamp).toLocaleDateString('en-CA', {
                    timeZone: 'Asia/Bangkok'
                }); // Returns YYYY-MM-DD format

                if (!groupedData[bangkokDate]) {
                    groupedData[bangkokDate] = [];
                }

                // Add timestamp as punch time in Bangkok timezone
                const time = new Date(record.timestamp).toLocaleTimeString('th-TH', {
                    hour: '2-digit',
                    minute: '2-digit',
                    timeZone: 'Asia/Bangkok'
                });
                groupedData[bangkokDate].push(time);
            }
        });

        // Sort dates in descending order (newest first)
        const sortedDates = Object.keys(groupedData).sort((a, b) => b.localeCompare(a));

        // Render table rows
        tableBody.innerHTML = sortedDates.map(date => {
            const formattedDate = this.formatDate(date);
            const times = [...new Set(groupedData[date])].sort(); // Remove duplicates and sort
            const timeDisplay = times.join('\n');

            return `
                <tr>
                    <td>${formattedDate}</td>
                    <td class="time-entries" style="white-space: pre-line;">${timeDisplay}</td>
                </tr>
            `;
        }).join('');
    }

    formatDate(dateString) {
        const date = new Date(dateString);
        const day = date.getDate().toString().padStart(2, '0');
        const month = (date.getMonth() + 1).toString().padStart(2, '0');
        const year = date.getFullYear();
        return `${day}/${month}/${year}`;
    }

    showNoDataMessage(message) {
        const tableBody = document.getElementById('attendanceTableBody');
        tableBody.innerHTML = `
            <tr>
                <td colspan="2" class="no-data">${escapeHtml(message)}</td>
            </tr>
        `;
    }

    showLoading(show) {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) {
            overlay.style.display = show ? 'flex' : 'none';
        }
    }
}

// Initialize when DOM is ready and config is loaded
let attendanceManager;
document.addEventListener('DOMContentLoaded', async () => {
    // Wait for configuration to be loaded
    await appConfig.loadConfig();
    attendanceManager = new IndividualAttendanceManager();
    await attendanceManager.initialize();
});