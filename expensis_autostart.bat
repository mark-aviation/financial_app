@echo off
setlocal EnableDelayedExpansion
cd /d "C:\Users\gerom\Videos\expensis"
echo [%date% %time%] Starting >> "C:\Users\gerom\Videos\expensis\expensis_startup.log"
set READY=0
for /L %%i in (1,1,30) do (
    if !READY!==0 (
        netstat -an 2>nul | find "3306" | find "LISTENING" >nul
        if !errorlevel!==0 (
            set READY=1
            echo [%date% %time%] MySQL ready >> "C:\Users\gerom\Videos\expensis\expensis_startup.log"
        ) else (
            echo [%date% %time%] Waiting MySQL %%i/30 >> "C:\Users\gerom\Videos\expensis\expensis_startup.log"
            timeout /t 3 /nobreak >nul
        )
    )
)
echo [%date% %time%] Launching API >> "C:\Users\gerom\Videos\expensis\expensis_startup.log"
"C:\Users\gerom\.pyenv\pyenv-win\versions\3.12.4\python.exe" "C:\Users\gerom\Videos\expensis\api.py" >> "C:\Users\gerom\Videos\expensis\expensis_startup.log" 2>&1
echo [%date% %time%] API stopped >> "C:\Users\gerom\Videos\expensis\expensis_startup.log"
