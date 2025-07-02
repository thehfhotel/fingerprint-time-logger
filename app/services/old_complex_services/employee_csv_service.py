"""
Employee CSV Import Service for Unified Employee Model

This service handles importing and syncing employee data from CSV files,
particularly the userid.csv file that contains Thai names.
"""

import csv
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from app.models.models import Employee
from app.core.database import get_db


class EmployeeCSVService:
    """Service for handling employee CSV operations"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def import_from_userid_csv(self, csv_file_path: str) -> Dict[str, int]:
        """
        Import/sync employees from userid.csv with Thai names
        
        CSV Format expected:
        USERID,Badgenumber,Name,ชื่อไทย
        
        Returns:
            Dict with counts of created, updated, and skipped records
        """
        results = {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0
        }
        
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row_num, row in enumerate(reader, start=2):  # Start at 2 for header
                    try:
                        badge_number = row.get('Badgenumber', '').strip()
                        thai_name = row.get('ชื่อไทย', '').strip() or None
                        english_name = row.get('Name', '').strip() or None
                        
                        if not badge_number:
                            print(f"Row {row_num}: Skipping row with empty badge number")
                            results["skipped"] += 1
                            continue
                        
                        # Check if employee exists
                        employee = self.db.query(Employee).filter(
                            Employee.badge_number == badge_number
                        ).first()
                        
                        if employee:
                            # Update existing employee
                            updated = False
                            
                            if thai_name and employee.thai_name != thai_name:
                                employee.thai_name = thai_name
                                updated = True
                            
                            if english_name and employee.english_name != english_name:
                                employee.english_name = english_name
                                updated = True
                            
                            # Update display name based on Thai name preference
                            new_display_name = thai_name if thai_name else f"พนักงาน {badge_number}"
                            if employee.display_name != new_display_name:
                                employee.display_name = new_display_name
                                updated = True
                            
                            if updated:
                                employee.updated_at = datetime.now()
                                results["updated"] += 1
                                print(f"Updated employee {badge_number}: {employee.display_name}")
                            else:
                                results["skipped"] += 1
                        else:
                            # Create new employee
                            display_name = thai_name if thai_name else f"พนักงาน {badge_number}"
                            
                            employee = Employee(
                                badge_number=badge_number,
                                english_name=english_name,
                                thai_name=thai_name,
                                display_name=display_name,
                                is_active=True,
                                is_hidden=False
                            )
                            
                            self.db.add(employee)
                            results["created"] += 1
                            print(f"Created employee {badge_number}: {display_name}")
                    
                    except Exception as e:
                        print(f"Row {row_num}: Error processing row - {str(e)}")
                        results["errors"] += 1
                        continue
                
                # Commit all changes
                self.db.commit()
                
        except Exception as e:
            print(f"Error reading CSV file: {str(e)}")
            results["errors"] += 1
            self.db.rollback()
        
        return results
    
    def export_to_csv(self, output_file_path: str, include_hidden: bool = False) -> int:
        """
        Export employee data to CSV format
        
        Args:
            output_file_path: Path for output CSV file
            include_hidden: Whether to include hidden employees
            
        Returns:
            Number of employees exported
        """
        query = self.db.query(Employee).filter(Employee.is_active == True)
        
        if not include_hidden:
            query = query.filter(Employee.is_hidden == False)
        
        employees = query.order_by(Employee.badge_number).all()
        
        with open(output_file_path, 'w', encoding='utf-8', newline='') as f:
            fieldnames = [
                'badge_number', 'english_name', 'thai_name', 'display_name',
                'department', 'position', 'job_role_id', 'is_active', 'is_hidden'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            writer.writeheader()
            for employee in employees:
                writer.writerow({
                    'badge_number': employee.badge_number,
                    'english_name': employee.english_name or '',
                    'thai_name': employee.thai_name or '',
                    'display_name': employee.display_name,
                    'department': employee.department or '',
                    'position': employee.position or '',
                    'job_role_id': employee.job_role_id or '',
                    'is_active': employee.is_active,
                    'is_hidden': employee.is_hidden
                })
        
        return len(employees)
    
    def sync_display_names(self) -> int:
        """
        Sync display names for all employees based on Thai name preference
        
        Returns:
            Number of employees updated
        """
        employees = self.db.query(Employee).all()
        updated_count = 0
        
        for employee in employees:
            new_display_name = (
                employee.thai_name if employee.thai_name 
                else f"พนักงาน {employee.badge_number}"
            )
            
            if employee.display_name != new_display_name:
                employee.display_name = new_display_name
                employee.updated_at = datetime.now()
                updated_count += 1
        
        if updated_count > 0:
            self.db.commit()
        
        return updated_count
    
    def get_employees_summary(self) -> Dict[str, int]:
        """
        Get summary statistics of employee data
        
        Returns:
            Dictionary with employee counts and statistics
        """
        total_employees = self.db.query(Employee).count()
        active_employees = self.db.query(Employee).filter(Employee.is_active == True).count()
        hidden_employees = self.db.query(Employee).filter(Employee.is_hidden == True).count()
        with_thai_names = self.db.query(Employee).filter(Employee.thai_name.isnot(None)).count()
        with_english_names = self.db.query(Employee).filter(Employee.english_name.isnot(None)).count()
        
        return {
            "total": total_employees,
            "active": active_employees,
            "hidden": hidden_employees,
            "with_thai_names": with_thai_names,
            "with_english_names": with_english_names,
            "visible": active_employees - hidden_employees
        }


def get_employee_csv_service(db: Session = None) -> EmployeeCSVService:
    """Factory function to get EmployeeCSVService instance"""
    if db is None:
        db = next(get_db())
    return EmployeeCSVService(db)