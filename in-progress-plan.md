# Employee Management System Implementation Plan

## Overview
Convert the "Thai Names" page into a comprehensive Employee Management page that manages employees extracted from ZK device with nickname configuration and role assignment.

## Current State Analysis ✅
- **Employee model** exists with `badge_number`, `thai_name`, `is_active`, `job_role_id`, `is_hidden`
- **JobRole model** exists with role management capabilities  
- **Thai Names API** provides basic CRUD operations
- **Responsive UI** with search, bulk editing capabilities

## Target Features
1. **Employee List**: Show all employees extracted from ZK device by Badgenumber
2. **Nickname Management**: Configure Thai/display names for each employee
3. **Role Assignment**: Assign roles (Maid, Office, Reception, Maintenance, Management)
4. **Status Management**: Mark employees as Active/Inactive (current vs ex-employee)
5. **Visibility Control**: Hide/show employees from normal view

## Implementation Phases

### Phase 1: Database Setup ✅
**Goal**: Ensure required job roles exist in database

**Tasks**:
- [ ] Create database migration for job roles seeding
- [ ] Seed 5 job roles: Maid, Office, Reception, Maintenance, Management
- [ ] Verify Employee model supports job_role_id relationship

**Files to modify**:
- `migrations/versions/[new]_seed_job_roles.py`

### Phase 2: Backend API Enhancement  
**Goal**: Create comprehensive employee management API

**Tasks**:
- [ ] Create new `app/api/employee_management.py`
- [ ] Implement EmployeeManagementResponse with role details
- [ ] Add bulk update operations
- [ ] Add device sync integration
- [ ] Create role assignment endpoints

**New API Endpoints**:
```
GET  /api/employees/management/              # List all employees with roles
PUT  /api/employees/management/{badge}       # Update individual employee  
POST /api/employees/management/bulk-update   # Bulk operations
GET  /api/employees/management/roles         # Get available roles
POST /api/employees/management/sync-device   # Sync from ZK device
```

**Files to create/modify**:
- `app/api/employee_management.py` (new)
- `app/main_unified.py` (add router)

### Phase 3: Frontend Page Conversion
**Goal**: Transform thai_names.html into employee_management.html

**Tasks**:
- [ ] Copy `static/thai_names.html` to `static/employee_management.html`
- [ ] Update page title and navigation
- [ ] Add role dropdown selectors
- [ ] Add active/inactive toggle switches  
- [ ] Implement bulk operations UI
- [ ] Add enhanced filtering (by role, status)
- [ ] Update statistics dashboard

**Enhanced UI Components**:
- Role dropdown with icons (🧹 Maid, 🏢 Office, 📞 Reception, 🔧 Maintenance, 👔 Management)
- Active/Inactive toggle switches
- Bulk selection and operations
- Enhanced search and filtering
- Real-time status updates

**Files to create/modify**:
- `static/employee_management.html` (new)
- Update route in `app/main_unified.py`

### Phase 4: API Integration & Testing
**Goal**: Connect frontend with new backend APIs

**Tasks**:
- [ ] Update JavaScript to use new management APIs
- [ ] Implement role assignment functionality  
- [ ] Add bulk operations handlers
- [ ] Connect with real-time manager
- [ ] Add device sync integration
- [ ] Test all CRUD operations

**JavaScript Updates**:
- Replace thai-names API calls with management APIs
- Add role selection handlers
- Implement active/inactive toggles
- Add bulk operation functions
- Integrate with real-time-manager.js

### Phase 5: Navigation & Integration
**Goal**: Update application navigation and routing

**Tasks**:
- [ ] Update dashboard navigation links
- [ ] Update route handlers in main_unified.py
- [ ] Test navigation flow
- [ ] Update any references to thai-names page

**Files to modify**:
- `static/dashboard.html` (navigation links)
- `templates/dashboard.html` (navigation links)  
- `app/main_unified.py` (routes)

### Phase 6: Testing & Polish
**Goal**: Comprehensive testing and user experience improvements

**Tasks**:
- [ ] Test all employee management operations
- [ ] Test device sync functionality
- [ ] Test bulk operations
- [ ] Test responsive design
- [ ] Run existing test suite
- [ ] Add any missing error handling

## Technical Specifications

### Employee Management Data Model
```python
class EmployeeManagementResponse(BaseModel):
    id: int
    badge_number: str
    nickname: str  # thai_name or display_name
    english_name: Optional[str]
    role: Optional[str]  # role_name from JobRole
    role_display_name: Optional[str]
    is_active: bool
    is_hidden: bool
    last_attendance: Optional[str]
    created_at: str
    updated_at: str
```

### Job Roles (5 Required Roles)
```sql
maid        -> 🧹 Maid (Housekeeping)
office      -> 🏢 Office (Administration)  
reception   -> 📞 Reception (Customer Service)
maintenance -> 🔧 Maintenance (Technical)
management  -> 👔 Management (Leadership)
```

### Bulk Operations Support
- Bulk role assignment
- Bulk activate/deactivate employees
- Bulk hide/show employees
- Bulk nickname updates

### Real-time Integration
- Connect with existing real-time-manager.js
- Live updates for employee changes
- Device sync notifications
- Status change notifications

## Success Criteria

### Functional Requirements ✅
- [x] Display all employees from ZK device by badge number
- [ ] Allow nickname configuration for each employee
- [ ] Support role assignment (5 roles: Maid, Office, Reception, Maintenance, Management)  
- [ ] Enable active/inactive status management
- [ ] Provide hide/show visibility control
- [ ] Support bulk operations for efficiency
- [ ] Maintain real-time updates
- [ ] Integrate with device sync functionality

### Technical Requirements ✅
- [ ] Maintain single-user simplicity
- [ ] Use existing Employee and JobRole models
- [ ] Preserve real-time manager integration
- [ ] Keep responsive design for mobile use
- [ ] Maintain test compatibility
- [ ] Follow existing code patterns and styling

### User Experience Requirements ✅
- [ ] Intuitive role selection with visual icons
- [ ] Clear active/inactive status indicators
- [ ] Efficient bulk operations
- [ ] Fast search and filtering
- [ ] Responsive design for all screen sizes
- [ ] Clear feedback for all operations

## Implementation Notes

### Maintaining Backward Compatibility
- Keep existing thai-names API endpoints for transition period
- Ensure existing attendance functionality continues working
- Maintain database schema compatibility

### Performance Considerations
- Use same real-time refresh patterns (30-second updates)
- Efficient bulk operations with single transactions
- Minimize API calls through intelligent caching of role data

### Security & Data Integrity
- Validate all role assignments against existing JobRole records
- Maintain referential integrity for job_role_id foreign keys
- Preserve existing employee data during migration

---

**Status**: 📋 Plan Complete - Ready for Implementation
**Next Step**: Phase 1 - Database Setup (Job Roles Seeding)