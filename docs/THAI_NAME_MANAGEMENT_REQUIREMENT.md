# Thai Name Management Requirement

## Overview
Add a new administrative page to manage Thai name mappings for employee badge numbers. This replaces the current CSV-based approach with a dynamic, database-driven solution for better maintainability and user experience.

## Business Requirements

### Primary Requirement
**Thai Name Management Page**: Create a web interface for managing employee Thai name mappings where users can view, edit, and save Thai names associated with badge numbers.

### Functional Requirements

#### FR-1: Thai Name List Display
- **Description**: Display a list of all badge numbers with their current Thai names
- **Input**: None (auto-loaded from database)
- **Output**: Table/list showing Badge Number | Current Thai Name | Actions
- **Business Value**: Provides visibility into all employee name mappings

#### FR-2: Inline Thai Name Editing
- **Description**: Allow users to edit Thai names directly in the interface
- **Input**: Click on Thai name field to make it editable
- **Output**: Editable text field with current Thai name value
- **Validation**: 
  - Thai name cannot be empty
  - Support Thai Unicode characters (UTF-8)
  - Maximum length: 100 characters
- **Business Value**: Easy maintenance of employee names without technical intervention

#### FR-3: Bulk Save Functionality
- **Description**: Save all edited Thai names in a single operation
- **Input**: Click "Save All Changes" button
- **Output**: Success/error confirmation message
- **Behavior**: 
  - Only save modified names (delta changes)
  - Rollback all changes if any save operation fails
  - Show loading indicator during save operation
- **Business Value**: Efficient batch updates for multiple employee names

#### FR-4: Badge Number Auto-Discovery
- **Description**: Automatically discover new badge numbers from attendance records
- **Input**: Attendance data from ZKTeco device
- **Output**: New badge numbers added to Thai name management list
- **Default Behavior**: New badge numbers get default Thai name: "พนักงาน {badge_number}"
- **Business Value**: No manual addition of new employees required

### Technical Requirements

#### TR-1: Database Integration
- **Current State**: Thai names stored in `userid.csv` file
- **Target State**: Thai names stored in database table `employee_thai_names`
- **Migration**: Import existing CSV data into database during upgrade
- **Persistence**: All changes immediately saved to database

#### TR-2: API Endpoints
- **GET /api/thai-names**: Retrieve all badge number → Thai name mappings
- **PUT /api/thai-names**: Update multiple Thai name mappings
- **POST /api/thai-names/sync**: Sync new badge numbers from attendance data

#### TR-3: Dashboard Integration
- **Current**: Dashboard reads Thai names from CSV file
- **Target**: Dashboard reads Thai names from database
- **Fallback**: If no Thai name in database, use "พนักงาน {badge_number}"

#### TR-4: Data Validation
- **Unicode Support**: Full Thai character support (UTF-8)
- **Input Sanitization**: Prevent XSS and SQL injection
- **Data Integrity**: Ensure badge numbers remain unique

## User Interface Requirements

### UI-1: Thai Name Management Page Layout
```
┌─────────────────────────────────────────────────────────────┐
│ 📝 Thai Name Management                    🔄 Sync New IDs │
├─────────────────────────────────────────────────────────────┤
│ Total Employees: 14                    🔍 Search: [______] │
├─────────────────────────────────────────────────────────────┤
│ Badge Number │ Current Thai Name        │ Actions           │
├─────────────────────────────────────────────────────────────┤
│ 105          │ [ไกด์                  ] │ ✏️ Edit          │
│ 106          │ [พราว                  ] │ ✏️ Edit          │
│ 107          │ [ดรีม                  ] │ ✏️ Edit          │
│ 109          │ [ช่างเก่ง              ] │ ✏️ Edit          │
│ ...          │ ...                     │ ...              │
├─────────────────────────────────────────────────────────────┤
│                                   💾 Save All Changes       │
└─────────────────────────────────────────────────────────────┘
```

### UI-2: Navigation Integration
- **Dashboard Menu**: Add "Thai Names" navigation link
- **Route**: `/thai-names` 
- **Permission**: Single super-user (no authentication required)

### UI-3: Responsive Design
- **Desktop**: Table layout with inline editing
- **Mobile**: Card-based layout with modal editing
- **Accessibility**: Keyboard navigation, screen reader support

## Implementation Plan

### Phase 1: Database & API Foundation (Day 1)
1. **Database Schema**: Create `employee_thai_names` table
2. **Migration Script**: Import existing CSV data to database  
3. **API Endpoints**: Implement CRUD operations for Thai names
4. **Data Validation**: Add input validation and sanitization

### Phase 2: Frontend Interface (Day 2)  
1. **Page Layout**: Create Thai name management page structure
2. **Inline Editing**: Implement editable Thai name fields
3. **Save Logic**: Add bulk save functionality with validation
4. **Navigation**: Integrate with existing dashboard menu

### Phase 3: Integration & Testing (Day 3)
1. **Dashboard Update**: Modify dashboard to use database Thai names
2. **Auto-Discovery**: Implement badge number sync from attendance
3. **Testing**: End-to-end workflow testing
4. **Documentation**: User guide and technical documentation

### Phase 4: Production Deployment (Day 4)
1. **Migration**: Deploy database changes to production
2. **Data Import**: Import existing CSV data
3. **Monitoring**: Verify all functionality works correctly
4. **Cleanup**: Remove CSV dependency from dashboard

## Database Schema Design

### New Table: `employee_thai_names`
```sql
CREATE TABLE employee_thai_names (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    badge_number VARCHAR(50) UNIQUE NOT NULL,
    thai_name VARCHAR(100) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast lookups
CREATE INDEX idx_thai_names_badge ON employee_thai_names(badge_number);
CREATE INDEX idx_thai_names_active ON employee_thai_names(is_active);
```

### Migration from CSV
```sql
-- Insert existing CSV data
INSERT INTO employee_thai_names (badge_number, thai_name) VALUES
('105', 'ไกด์'),
('106', 'พราว'),
('107', 'ดรีม'),
('109', 'ช่างเก่ง'),
('123', 'น้อยโหน่ง'),
('421', 'วิณัฐ'),
('1188', 'พนักงาน 1188'),
('2522', 'หมวย'),
('2537', 'รีวิว'),
('2541', 'สะเบ้นซ์'),
('2559', 'พี่หญิง'),
('37', 'จิ๋ม'),
('22', 'พรทิพย์'),
('10468', 'พนักงาน 10468');
```

## API Specification

### GET /api/thai-names
**Response**:
```json
{
  "data": [
    {
      "id": 1,
      "badge_number": "105",
      "thai_name": "ไกด์",
      "is_active": true,
      "updated_at": "2025-06-29T02:00:00Z"
    }
  ],
  "total": 14
}
```

### PUT /api/thai-names
**Request**:
```json
{
  "updates": [
    {
      "badge_number": "105",
      "thai_name": "ไกด์ (อัปเดต)"
    },
    {
      "badge_number": "106", 
      "thai_name": "พราวใหม่"
    }
  ]
}
```

**Response**:
```json
{
  "success": true,
  "updated_count": 2,
  "message": "Thai names updated successfully"
}
```

### POST /api/thai-names/sync
**Description**: Sync new badge numbers from attendance records
**Response**:
```json
{
  "success": true,
  "new_badge_numbers": ["999", "1001"],
  "total_synced": 2
}
```

## Success Criteria

### Functional Success
- ✅ Users can view all badge numbers and Thai names in one page
- ✅ Users can edit Thai names inline without page refresh  
- ✅ Users can save multiple Thai name changes in one operation
- ✅ New badge numbers automatically appear in management page
- ✅ Dashboard displays Thai names from database (not CSV)

### Technical Success  
- ✅ Database migration completed without data loss
- ✅ API endpoints respond within 500ms for typical operations
- ✅ Full Unicode Thai character support
- ✅ Input validation prevents invalid data entry
- ✅ Error handling with user-friendly messages

### Business Success
- ✅ Super-user can maintain employee names without technical knowledge
- ✅ No developer intervention needed for Thai name updates
- ✅ System automatically handles new employees from attendance
- ✅ Backup/restore capabilities for Thai name data

## Risk Mitigation

### Data Loss Prevention
- **Backup Strategy**: Export current CSV before migration
- **Rollback Plan**: Keep CSV file as backup during transition
- **Validation**: Verify all CSV data imported correctly

### Performance Considerations
- **Database Indexes**: Optimize badge number lookups
- **Caching**: Cache Thai names in dashboard for performance  
- **Batch Operations**: Minimize database calls during bulk saves

### User Experience
- **Loading States**: Show progress during save operations
- **Error Recovery**: Clear error messages and retry options
- **Keyboard Support**: Full keyboard navigation for accessibility

## Integration with Current System

### Modified Components
1. **Dashboard (`dashboard_app.py`)**: 
   - Replace CSV reading with database queries
   - Add fallback logic for missing Thai names

2. **Database Models (`app/models/models.py`)**:
   - Add `EmployeeThaiName` model
   - Add relationship to existing models if needed

3. **API (`app/main.py`)**:
   - Add Thai name management endpoints
   - Add input validation middleware

4. **Frontend Navigation**:
   - Add "Thai Names" menu item to dashboard
   - Update routing for new page

### Backward Compatibility
- **CSV Support**: Keep CSV reading as fallback during transition
- **API Compatibility**: Maintain existing dashboard API structure
- **Data Format**: Preserve exact Thai name strings from CSV

---

**Priority**: High - This feature directly improves system maintainability and user experience for the primary super-user workflow.

**Estimated Effort**: 4 days (1 day per phase)

**Dependencies**: Current production server and database infrastructure