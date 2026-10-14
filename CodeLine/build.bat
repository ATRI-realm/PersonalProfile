@echo off
REM ==========================================================
REM  代码行统计工具 -- Windows 一键编译脚本
REM  需要已安装 MinGW / TDM-GCC，且 g++ 在 PATH 中
REM ==========================================================

g++ -std=c++11 -O2 -Wall -o loc.exe loc.cpp
if %errorlevel% neq 0 (
    echo.
    echo [FAILED] 编译失败，请确认已安装 g++ 并加入 PATH。
    pause
    exit /b 1
)

echo.
echo [OK] 编译成功，生成 loc.exe
echo.
echo 用法示例：
echo     loc.exe                   统计当前目录
echo     loc.exe D:\myproject      统计指定目录
echo     loc.exe D:\myproject -s   简化模式（blank/comment 显示为 /）
echo.
pause
