@echo off 
cd C:\Users\emi\fiji_ferry_booking 
call venv\Scripts\activate 
python manage.py update_schedules 
