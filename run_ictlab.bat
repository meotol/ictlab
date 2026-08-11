@echo off
cd /d C:\projects\ictlab
call .venv\Scripts\activate
flask --app __init__:create_app run
pause