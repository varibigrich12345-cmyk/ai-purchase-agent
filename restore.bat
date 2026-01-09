@echo off
chcp 65001 > nul
echo ========================================
echo 🔙 ВОССТАНОВЛЕНИЕ ИЗ БЭКАПА
echo ========================================
echo.

cd /d "C:\Users\user\Documents\ai-purchase-agent"

echo Выберите метод восстановления:
echo.
echo [1] Git откат (последний коммит)
echo [2] Git откат (выбрать коммит)
echo [3] Файловый бэкап (последний)
echo [4] Файловый бэкап (выбрать)
echo [0] Отмена
echo.

set /p choice="Ваш выбор: "

if "%choice%"=="1" goto git_last
if "%choice%"=="2" goto git_choose
if "%choice%"=="3" goto file_last
if "%choice%"=="4" goto file_choose
if "%choice%"=="0" goto cancel
goto cancel

:: ====================================
:: GIT ОТКАТ НА 1 КОММИТ НАЗАД
:: ====================================
:git_last
echo.
echo 🔄 Откат Git на последний коммит...
echo.
git log --oneline -5
echo.
set /p confirm="Откатиться на 1 коммит назад? (y/n): "
if /i not "%confirm%"=="y" goto cancel

git reset --hard HEAD~1
echo.
echo ✅ Откат выполнен!
goto end

:: ====================================
:: GIT ВЫБОР КОММИТА
:: ====================================
:git_choose
echo.
echo История коммитов:
echo.
git log --oneline -10
echo.
set /p commit_hash="Введите хеш коммита для отката: "

git reset --hard %commit_hash%
echo.
echo ✅ Откат выполнен!
goto end

:: ====================================
:: ФАЙЛОВЫЙ БЭКАП - ПОСЛЕДНИЙ
:: ====================================
:file_last
echo.
echo 📁 Поиск последнего бэкапа...

for /f "delims=" %%i in ('dir /B /AD /O-D "C:\Users\user\Documents\ai-purchase-agent-backups\backup_*" 2^>nul') do (
    set backup_name=%%i
    goto found_last
)

echo ❌ Бэкапы не найдены!
goto cancel

:found_last
set backup_path=C:\Users\user\Documents\ai-purchase-agent-backups\%backup_name%

echo ✅ Найден: %backup_name%
echo.
set /p confirm="Восстановить из этого бэкапа? (y/n): "
if /i not "%confirm%"=="y" goto cancel

goto do_restore

:: ====================================
:: ФАЙЛОВЫЙ БЭКАП - ВЫБОР
:: ====================================
:file_choose
echo.
echo Доступные бэкапы:
echo.
dir /B /AD /O-D "C:\Users\user\Documents\ai-purchase-agent-backups\backup_*" 2>nul
echo.
set /p backup_name="Введите имя папки бэкапа: "

set backup_path=C:\Users\user\Documents\ai-purchase-agent-backups\%backup_name%

if not exist "%backup_path%" (
    echo ❌ Бэкап не найден!
    goto cancel
)

goto do_restore

:: ====================================
:: ВЫПОЛНЕНИЕ ВОССТАНОВЛЕНИЯ
:: ====================================
:do_restore
echo.
echo 🔄 Остановка процессов...
taskkill /F /IM python.exe 2>nul

echo 📦 Восстановление файлов...
xcopy "%backup_path%\*.py" "." /Y /Q
xcopy "%backup_path%\sites\*" "sites\" /Y /Q
xcopy "%backup_path%\backend\*" "backend\" /Y /S /Q
xcopy "%backup_path%\tasks.db" "." /Y /Q 2>nul

echo.
echo ✅ Восстановление завершено!
goto end

:: ====================================
:cancel
echo.
echo ❌ Отменено
goto end

:end
echo.
echo ========================================
echo Запустите:
echo   python main.py
echo   python worker.py
echo ========================================
echo.
pause
