@echo off
cls
echo ========================================
echo        SISTEMA BEKAPOV AI AGENT
echo ========================================
echo.

:menu
echo Viberite deystvie:
echo.
echo [1] Sozdat novyy bekap (sohranit)
echo [2] Pokazat vse bekapy
echo [3] Otkatitsya nazad
echo [4] Chto izmenilos
echo [5] PERVYY ZAPUSK (inicializaciya)
echo [0] Vyhod
echo.
set /p choice="Vash vybor: "

if "%choice%"=="1" goto create_backup
if "%choice%"=="2" goto list_backups
if "%choice%"=="3" goto restore_backup
if "%choice%"=="4" goto show_changes
if "%choice%"=="5" goto init_git
if "%choice%"=="0" exit
goto menu

:init_git
echo.
echo Inicializaciya Git...
git init
if errorlevel 1 (
    echo OSHIBKA! Git ne ustanovlen ili ne nayden.
    pause
    goto menu
)
git add .
git commit -m "Pervyy kommit - rabochaya versiya s parserom zzap.ru"
echo.
echo GOTOVO! Teper ispolzuyte punkt [1] dlya sohraneniya
echo.
pause
goto menu

:create_backup
echo.
set /p message="Chto vy sdelali? (naprimer: Dobavil Exist): "
if "%message%"=="" set message=Bekap ot %date% %time%

git add .
git commit -m "%message%"

if errorlevel 1 (
    echo.
    echo Net izmeneniy dlya sohraneniya ili oshibka
) else (
    echo.
    echo SOHRANENO!
    echo %message%
)
echo.
pause
goto menu

:list_backups
echo.
echo VSE VASHI SOHRANENIYA:
echo ========================================
git log --oneline --all --decorate -15
echo ========================================
echo.
echo Samoe novoe sverhu
echo.
pause
goto menu

:restore_backup
echo.
echo VNIMANIE! Vse izmeneniya budut poterany!
echo.
echo Snachala posmotrite spisok (punkt [2])
echo.
set /p restore="Vvedite 7 simvolov ID ili Enter dlya otmeny: "

if "%restore%"=="" goto menu

git reset --hard %restore%
echo.
echo Otkat vypolnen!
pause
goto menu

:show_changes
echo.
echo CHTO IZMENILOS:
echo ========================================
git status -s
echo ========================================
echo.
pause
goto menu
