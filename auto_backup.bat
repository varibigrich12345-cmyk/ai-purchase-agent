@echo off
cd /d "C:\Users\user\Documents\ai-purchase-agent"

git add .
git commit -m "Auto-backup pered vyklyucheniem %date% %time%"

if errorlevel 1 (
    echo Net izmeneniy
) else (
    echo Backup sozdan!
)

timeout /t 3
