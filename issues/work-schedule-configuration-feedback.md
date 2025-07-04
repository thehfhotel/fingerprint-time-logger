#1
Title: Time configuration is not complete
Expected behavior:
1. click to select start time
2. click to select end time
3. click save
4. time saved for the role
Found issues:
1. nothing happen when click on the start time (but can use keyboard to change value)
2. nothing happen when click on the end time (but can use keyboard to change value)
3. click save got error: ❌ บันทึกเวลาไม่สำเร็จ: Failed to save time settings: 404 - {"detail":"Not Found"}
3.1 here's error from browser console:
--start of error--
work-schedules:1556 saveTimeSettings called
work-schedules:1557 currentRole: maid
work-schedules:1565 startTimeEl: <input type=​"time" class=​"form-control" id=​"roleStartTime" required>​
work-schedules:1566 endTimeEl: <input type=​"time" class=​"form-control" id=​"roleEndTime" required>​
work-schedules:1575 startTime: 07:00
work-schedules:1576 endTime: 16:00
work-schedules:1584 API URL: /api/employee-schedules/roles/maid/time-settings
work-schedules:1586  PUT http://192.168.100.228:5000/api/employee-schedules/roles/maid/time-settings 404 (Not Found)
saveTimeSettings @ work-schedules:1586
onclick @ work-schedules:751
work-schedules:1592 Response status: 404
work-schedules:1608 Error saving time settings: Error: Failed to save time settings: 404 - {"detail":"Not Found"}
    at saveTimeSettings (work-schedules:1605:27)
saveTimeSettings @ work-schedules:1608
await in saveTimeSettings
onclick @ work-schedules:751
--end of error--
Status: Pending fix
Solution:

#2
Title: cannot add employee to Monthly Schedule
Expected behavior: click add employee button and a new row appear to select employee
Status: Pending fix
Issue: when click add employee, got this error: ไม่มีพนักงานที่สามารถเพิ่มได้ พนักงานทั้งหมดได้รับการมอบหมายแล้ว
Solution:

#3
Title: switch from Maid to Office role got error in browser console
Expected behavior: switching between roles will change 1. Time Configuration and 2.Monthly Schedule data accordingly
Status: Pending fix
Issue: when switch from Maid role to Office role, got error in browser console
--start of error--
work-schedules:1246  GET http://192.168.100.228:5000/api/employee-schedules/roles/office/time-settings 404 (Not Found)
loadEmployeeScheduleData @ work-schedules:1246
showRoleContent @ work-schedules:886
(anonymous) @ work-schedules:854
work-schedules:1255  GET http://192.168.100.228:5000/api/employee-schedules/roles/office/available-employees 404 (Not Found)
loadEmployeeScheduleData @ work-schedules:1255
await in loadEmployeeScheduleData
showRoleContent @ work-schedules:886
(anonymous) @ work-schedules:854
work-schedules:1277  GET http://192.168.100.228:5000/api/employee-schedules/monthly/2025/7?role=office 404 (Not Found)
loadMonthlySchedule @ work-schedules:1277
loadEmployeeScheduleData @ work-schedules:1261
await in loadEmployeeScheduleData
showRoleContent @ work-schedules:886
(anonymous) @ work-schedules:854
--end of error--
