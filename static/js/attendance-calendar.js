/**
 * Attendance Calendar JavaScript
 * Interactive monthly calendar with color-coded attendance status
 */

class AttendanceCalendar {
    constructor() {
        this.currentYear = new Date().getFullYear();
        this.currentMonth = new Date().getMonth() + 1;
        this.attendanceData = null;
        this.config = null;
        this.apiBaseUrl = `http://${window.location.hostname}:8000`; // API server port
        
        // DOM elements
        this.loadingOverlay = document.getElementById('loadingOverlay');
        this.currentMonthElement = document.getElementById('currentMonth');
        this.tableBody = document.getElementById('attendanceTableBody');
        
        this.init();
    }
    
    async init() {
        console.log('Initializing Attendance Calendar...');
        
        // Load configuration first
        await this.loadConfig();
        
        // Bind event listeners
        this.bindEvents();
        
        // Load initial calendar data
        await this.loadCalendarData();
        
        // Render the calendar
        this.renderCalendar();
        
        console.log('Attendance Calendar initialized successfully');
    }
    
    bindEvents() {
        // Navigation buttons
        document.getElementById('prevMonth').addEventListener('click', () => {
            this.navigateMonth(-1);
        });
        
        document.getElementById('nextMonth').addEventListener('click', () => {
            this.navigateMonth(1);
        });
        
        // Action buttons
        document.getElementById('exportBtn').addEventListener('click', () => {
            this.exportCalendar();
        });
        
        document.getElementById('printBtn').addEventListener('click', () => {
            this.printCalendar();
        });
        
        document.getElementById('refreshBtn').addEventListener('click', () => {
            this.refreshCalendar();
        });
        
        // Keyboard navigation
        document.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowLeft' && e.ctrlKey) {
                this.navigateMonth(-1);
            } else if (e.key === 'ArrowRight' && e.ctrlKey) {
                this.navigateMonth(1);
            } else if (e.key === 'F5') {
                e.preventDefault();
                this.refreshCalendar();
            }
        });
    }
    
    async loadConfig() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/attendance/calendar/config`);
            if (response.ok) {
                this.config = await response.json();
                console.log('Calendar config loaded:', this.config);
            } else {
                console.error('Failed to load calendar config');
                this.config = this.getDefaultConfig();
            }
        } catch (error) {
            console.error('Error loading config:', error);
            this.config = this.getDefaultConfig();
        }
    }
    
    getDefaultConfig() {
        return {
            status_colors: {
                'perfect': '#4CAF50',
                'minor_issue': '#FF9800',
                'violation': '#F44336',
                'absent': '#E0E0E0',
                'non_working': '#2196F3',
                'partial': '#FF5722'
            },
            status_symbols: {
                'perfect': '✓',
                'minor_issue': '⚠',
                'violation': '✗',
                'absent': '-',
                'non_working': 'H',
                'partial': '◐'
            }
        };
    }
    
    async loadCalendarData() {
        this.showLoading(true);
        
        try {
            const url = `${this.apiBaseUrl}/api/attendance/calendar/${this.currentYear}/${this.currentMonth}`;
            console.log('Loading calendar data from:', url);
            
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            this.attendanceData = await response.json();
            console.log('Calendar data loaded:', this.attendanceData);
            
        } catch (error) {
            console.error('Failed to load calendar data:', error);
            this.showError('Failed to load attendance data. Please try again.');
            this.attendanceData = this.getEmptyCalendarData();
        } finally {
            this.showLoading(false);
        }
    }
    
    getEmptyCalendarData() {
        const monthName = new Date(this.currentYear, this.currentMonth - 1).toLocaleString('default', { month: 'long' });
        const daysInMonth = new Date(this.currentYear, this.currentMonth, 0).getDate();
        
        return {
            year: this.currentYear,
            month: this.currentMonth,
            month_name: monthName,
            days_in_month: daysInMonth,
            employees: [],
            holidays: [],
            weekends: [],
            working_days: [],
            statistics: {
                total_employees: 0,
                total_working_days: 0,
                perfect_attendance_rate: 0,
                punctuality_rate: 0,
                average_late_minutes: 0,
                violation_count: 0,
                absent_count: 0,
                role_breakdown: []
            }
        };
    }
    
    renderCalendar() {
        this.updateHeader();
        this.renderTable();
        this.renderStatistics();
    }
    
    updateHeader() {
        this.currentMonthElement.textContent = `${this.attendanceData.month_name} ${this.attendanceData.year}`;
    }
    
    renderTable() {
        // Clear existing table body
        this.tableBody.innerHTML = '';
        
        // Render table header with days
        this.renderTableHeader();
        
        // Render employee rows
        this.attendanceData.employees.forEach(employee => {
            const row = this.createEmployeeRow(employee);
            this.tableBody.appendChild(row);
        });
        
        // Handle empty state
        if (this.attendanceData.employees.length === 0) {
            this.renderEmptyState();
        }
    }
    
    renderTableHeader() {
        const table = document.querySelector('.attendance-table');
        const thead = table.querySelector('thead tr');
        
        // Clear existing day headers (keep employee header)
        const dayHeaders = thead.querySelectorAll('th:not(.employee-header)');
        dayHeaders.forEach(header => header.remove());
        
        // Add day headers
        for (let day = 1; day <= this.attendanceData.days_in_month; day++) {
            const th = document.createElement('th');
            
            // Get day of week
            const dayDate = new Date(this.attendanceData.year, this.attendanceData.month - 1, day);
            const dayOfWeek = dayDate.toLocaleDateString('en-US', { weekday: 'short' });
            
            // Format header with day number and day of week
            th.innerHTML = `<div class="day-number">${day}</div><div class="day-of-week">${dayOfWeek}</div>`;
            th.className = 'day-header';
            
            // Highlight payroll days (1st and 16th of each month)
            if (day === 1 || day === 16) {
                th.classList.add('payroll-day');
            }
            
            // Mark holidays
            if (this.attendanceData.holidays.includes(day)) {
                th.classList.add('holiday');
            }
            
            thead.appendChild(th);
        }
    }
    
    createEmployeeRow(employee) {
        const row = document.createElement('tr');
        
        // Employee name cell
        const nameCell = document.createElement('td');
        nameCell.textContent = employee.name;
        nameCell.className = 'employee-name';
        nameCell.title = `${employee.name}${employee.role ? ` (${employee.role})` : ''}`;
        row.appendChild(nameCell);
        
        // Daily attendance cells
        for (let day = 1; day <= this.attendanceData.days_in_month; day++) {
            const cell = document.createElement('td');
            const dayStr = day.toString();
            const attendanceData = employee.daily_attendance[dayStr];
            
            if (attendanceData) {
                cell.className = `attendance-cell status-${attendanceData.status}`;
                cell.textContent = this.getStatusSymbol(attendanceData.status);
                cell.style.backgroundColor = this.getStatusColor(attendanceData.status);
                
                // Add click handler for detailed view
                cell.addEventListener('click', () => {
                    this.showEmployeeDayDetail(employee.id, day);
                });
                
                // Add hover tooltip
                cell.addEventListener('mouseenter', (e) => {
                    this.showTooltip(e, attendanceData, employee.name);
                });
                
                cell.addEventListener('mouseleave', () => {
                    this.hideTooltip();
                });
                
                // Add keyboard accessibility
                cell.setAttribute('tabindex', '0');
                cell.setAttribute('role', 'button');
                cell.setAttribute('aria-label', 
                    `${employee.name} attendance on ${this.attendanceData.month_name} ${day}: ${attendanceData.status}`
                );
                
                cell.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        this.showEmployeeDayDetail(employee.id, day);
                    }
                });
                
            } else {
                cell.className = 'attendance-cell status-absent';
                cell.textContent = '-';
                cell.style.backgroundColor = this.getStatusColor('absent');
            }
            
            row.appendChild(cell);
        }
        
        return row;
    }
    
    renderEmptyState() {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = this.attendanceData.days_in_month + 1;
        cell.textContent = 'No employee data available for this month';
        cell.style.textAlign = 'center';
        cell.style.padding = '40px';
        cell.style.fontStyle = 'italic';
        cell.style.color = '#666';
        row.appendChild(cell);
        this.tableBody.appendChild(row);
    }
    
    getStatusSymbol(status) {
        return this.config.status_symbols[status] || '?';
    }
    
    getStatusColor(status) {
        return this.config.status_colors[status] || '#666666';
    }
    
    showTooltip(event, attendanceData, employeeName) {
        this.hideTooltip(); // Remove any existing tooltip
        
        const tooltip = document.createElement('div');
        tooltip.className = 'tooltip';
        tooltip.innerHTML = this.generateTooltipContent(attendanceData, employeeName);
        
        document.body.appendChild(tooltip);
        
        // Position tooltip
        const rect = event.target.getBoundingClientRect();
        const tooltipRect = tooltip.getBoundingClientRect();
        
        let left = rect.left + (rect.width / 2) - (tooltipRect.width / 2);
        let top = rect.top - tooltipRect.height - 10;
        
        // Adjust if tooltip goes off screen
        if (left < 0) left = 10;
        if (left + tooltipRect.width > window.innerWidth) {
            left = window.innerWidth - tooltipRect.width - 10;
        }
        if (top < 0) {
            top = rect.bottom + 10;
        }
        
        tooltip.style.left = left + 'px';
        tooltip.style.top = top + 'px';
    }
    
    generateTooltipContent(attendanceData, employeeName) {
        const formatTime = (timeStr) => {
            if (!timeStr) return 'N/A';
            try {
                return new Date(timeStr).toLocaleTimeString('th-TH', {
                    hour: '2-digit',
                    minute: '2-digit'
                });
            } catch {
                return timeStr;
            }
        };
        
        const statusText = {
            'perfect': 'Perfect',
            'minor_issue': 'Minor Issue',
            'violation': 'Major Violation',
            'absent': 'Absent',
            'non_working': 'Holiday/Weekend',
            'partial': 'Partial'
        }[attendanceData.status] || attendanceData.status;
        
        let content = `
            <strong>${employeeName}</strong><br>
            <strong>${attendanceData.date}</strong><br>
            Status: <span style="font-weight: bold;">${statusText}</span><br>
        `;
        
        if (attendanceData.check_in || attendanceData.check_out) {
            content += `
                Check-in: ${formatTime(attendanceData.check_in)}<br>
                Check-out: ${formatTime(attendanceData.check_out)}<br>
            `;
        }
        
        if (attendanceData.late_minutes > 0) {
            content += `Late: ${attendanceData.late_minutes} minutes<br>`;
        }
        
        if (attendanceData.early_departure_minutes > 0) {
            content += `Early departure: ${attendanceData.early_departure_minutes} minutes<br>`;
        }
        
        if (attendanceData.work_hours) {
            content += `Work hours: ${attendanceData.work_hours.toFixed(1)}h<br>`;
        }
        
        if (attendanceData.holiday_name) {
            content += `Holiday: ${attendanceData.holiday_name}<br>`;
        }
        
        if (attendanceData.notes) {
            content += `Notes: ${attendanceData.notes}`;
        }
        
        return content;
    }
    
    hideTooltip() {
        const existing = document.querySelector('.tooltip');
        if (existing) {
            existing.remove();
        }
    }
    
    renderStatistics() {
        const stats = this.attendanceData.statistics;
        
        document.getElementById('perfectRate').textContent = `${stats.perfect_attendance_rate.toFixed(1)}%`;
        document.getElementById('punctualityRate').textContent = `${stats.punctuality_rate.toFixed(1)}%`;
        document.getElementById('violationCount').textContent = stats.violation_count;
        document.getElementById('avgLateTime').textContent = `${stats.average_late_minutes.toFixed(1)} min`;
    }
    
    async navigateMonth(direction) {
        this.currentMonth += direction;
        
        if (this.currentMonth > 12) {
            this.currentMonth = 1;
            this.currentYear++;
        } else if (this.currentMonth < 1) {
            this.currentMonth = 12;
            this.currentYear--;
        }
        
        await this.loadCalendarData();
        this.renderCalendar();
    }
    
    async refreshCalendar() {
        console.log('Refreshing calendar data...');
        await this.loadCalendarData();
        this.renderCalendar();
    }
    
    async showEmployeeDayDetail(employeeId, day) {
        try {
            const url = `${this.apiBaseUrl}/api/attendance/calendar/${this.currentYear}/${this.currentMonth}/${day}/employee/${employeeId}`;
            const response = await fetch(url);
            
            if (response.ok) {
                const detail = await response.json();
                this.displayEmployeeDetail(detail);
            } else {
                console.error('Failed to load employee detail');
            }
        } catch (error) {
            console.error('Error loading employee detail:', error);
        }
    }
    
    displayEmployeeDetail(detail) {
        // Create modal or popup to show detailed information
        const modalContent = `
            <div style="background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); max-width: 400px;">
                <h3>${detail.employee_name}</h3>
                <p><strong>Date:</strong> ${detail.date}</p>
                <p><strong>Status:</strong> ${detail.status}</p>
                <p><strong>Check-in:</strong> ${detail.check_in ? new Date(detail.check_in).toLocaleTimeString() : 'N/A'}</p>
                <p><strong>Check-out:</strong> ${detail.check_out ? new Date(detail.check_out).toLocaleTimeString() : 'N/A'}</p>
                ${detail.late_minutes > 0 ? `<p><strong>Late:</strong> ${detail.late_minutes} minutes</p>` : ''}
                ${detail.work_hours ? `<p><strong>Work Hours:</strong> ${detail.work_hours.toFixed(1)}h</p>` : ''}
                ${detail.notes ? `<p><strong>Notes:</strong> ${detail.notes}</p>` : ''}
                <button onclick="this.parentElement.parentElement.remove()" style="margin-top: 15px; padding: 8px 16px; background: #667eea; color: white; border: none; border-radius: 4px; cursor: pointer;">Close</button>
            </div>
        `;
        
        const modal = document.createElement('div');
        modal.style.cssText = `
            position: fixed; top: 0; left: 0; width: 100%; height: 100%; 
            background: rgba(0,0,0,0.5); display: flex; justify-content: center; 
            align-items: center; z-index: 10000;
        `;
        modal.innerHTML = modalContent;
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.remove();
        });
        
        document.body.appendChild(modal);
    }
    
    async exportCalendar() {
        try {
            const url = `${this.apiBaseUrl}/api/attendance/calendar/${this.currentYear}/${this.currentMonth}/export?format=csv`;
            const response = await fetch(url);
            
            if (response.ok) {
                const blob = await response.blob();
                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = downloadUrl;
                a.download = `attendance_calendar_${this.currentYear}_${this.currentMonth}.csv`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(downloadUrl);
                document.body.removeChild(a);
            } else {
                console.error('Export failed');
            }
        } catch (error) {
            console.error('Export error:', error);
        }
    }
    
    printCalendar() {
        window.print();
    }
    
    showLoading(show) {
        if (this.loadingOverlay) {
            this.loadingOverlay.style.display = show ? 'flex' : 'none';
        }
    }
    
    showError(message) {
        // Simple error display
        console.error(message);
        
        // You could create a more sophisticated error display here
        const errorDiv = document.createElement('div');
        errorDiv.style.cssText = `
            position: fixed; top: 20px; right: 20px; background: #f44336; 
            color: white; padding: 15px; border-radius: 5px; z-index: 1000;
            max-width: 300px;
        `;
        errorDiv.textContent = message;
        
        document.body.appendChild(errorDiv);
        
        setTimeout(() => {
            if (errorDiv.parentNode) {
                errorDiv.parentNode.removeChild(errorDiv);
            }
        }, 5000);
    }
}

// Initialize calendar when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM loaded, initializing attendance calendar...');
    
    // Check if we're on the attendance calendar page
    if (document.querySelector('.attendance-table')) {
        window.attendanceCalendar = new AttendanceCalendar();
    }
});

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AttendanceCalendar;
}