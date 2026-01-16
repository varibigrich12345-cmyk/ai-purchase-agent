@echo off
chcp 65001 >nul
echo ========================================
echo  Запуск Chrome с Remote Debugging
echo  Порт: 9222
echo ========================================
echo.

:: Проверяем, не запущен ли уже Chrome с отладкой
netstat -ano | findstr ":9222" >nul 2>&1
if %errorlevel%==0 (
    echo [!] Chrome с портом 9222 уже запущен!
    echo [!] Закройте существующий процесс или используйте его.
    pause
    exit /b 1
)

:: Путь к Chrome (проверяем разные варианты)
set CHROME_PATH=

if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe
)
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
)
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe
)

if "%CHROME_PATH%"=="" (
    echo [ERROR] Chrome не найден!
    echo Проверьте установку Google Chrome.
    pause
    exit /b 1
)

echo [*] Найден Chrome: %CHROME_PATH%
echo [*] Запуск с remote-debugging-port=9222...
echo.

:: Запуск Chrome с отладкой
:: --user-data-dir задаёт отдельный профиль для отладки
start "" "%CHROME_PATH%" ^
    --remote-debugging-port=9222 ^
    --user-data-dir="%USERPROFILE%\ChromeDebugProfile" ^
    --disable-background-timer-throttling ^
    --disable-backgrounding-occluded-windows ^
    --disable-renderer-backgrounding ^
    --no-first-run ^
    --disable-default-apps

echo.
echo [OK] Chrome запущен!
echo [OK] Подключайтесь через CDP к ws://localhost:9222
echo.
echo Для проверки откройте: http://localhost:9222/json/version
echo.
pause
