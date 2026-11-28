@echo off
rem OSS Radar launcher (double-click). Keep every line above "chcp" ASCII-only.
setlocal
chcp 65001 >nul
title OSS Radar
cd /d "%~dp0"

rem Cùng cổng với `uv run poe dev` (pyproject.toml).
set "PORT=8765"
set "URL=http://127.0.0.1:%PORT%"
rem Để log tiếng Việt in ra cửa sổ này không bị vỡ chữ.
set "PYTHONUTF8=1"

echo.
echo  OSS Radar
echo  =========
echo.

where uv >nul 2>nul
if errorlevel 1 goto no_uv

rem Cổng đã có chương trình nghe: coi như app đang chạy ở cửa sổ khác, chỉ mở trình duyệt.
powershell -NoProfile -Command "try{(New-Object Net.Sockets.TcpClient('127.0.0.1',%PORT%)).Close();exit 0}catch{exit 1}"
if not errorlevel 1 goto already_running

if not exist ".env" echo  [Lưu ý] Chưa có file .env nên chưa có GITHUB_TOKEN: tool vẫn chạy nhưng quét rất chậm.
if not exist ".env" echo.

rem --frozen: cài đúng phiên bản trong uv.lock và không bao giờ tự ghi lại uv.lock.
echo  [1/3] Kiểm tra thư viện...
uv sync --frozen --quiet
if errorlevel 1 goto failed

echo  [2/3] Cập nhật cơ sở dữ liệu...
uv run --frozen python manage.py migrate --no-input -v 0
if errorlevel 1 goto failed

echo  [3/3] Mở web tại %URL%
echo.
echo  Cứ để cửa sổ này mở: tool tự quét hằng ngày và tự cập nhật dữ liệu trong lúc đang chạy.
echo  Muốn tắt tool thì đóng cửa sổ này. Lượt quét đang dở sẽ tự chạy tiếp ở lần mở sau.
echo.

rem Chờ máy chủ giữ được cổng (tối đa 60 giây) rồi mới mở trình duyệt, tránh trang "không kết nối được".
start "" /b powershell -NoProfile -Command "for($i=0;$i -lt 60;$i++){try{(New-Object Net.Sockets.TcpClient('127.0.0.1',%PORT%)).Close();Start-Process '%URL%';break}catch{Start-Sleep -Seconds 1}}"

rem --noreload: một tiến trình duy nhất, không tự khởi động lại giữa lượt quét khi file code thay đổi.
uv run --frozen python manage.py runserver 127.0.0.1:%PORT% --noreload

echo.
echo  OSS Radar đã dừng.
pause
exit /b 0

:already_running
echo  Cổng %PORT% đang có chương trình dùng, nhiều khả năng OSS Radar đang chạy ở một cửa sổ khác.
echo  Đang mở trình duyệt tới %URL%
start "" "%URL%"
rem Giữ cửa sổ 5 giây cho kịp đọc dòng báo ở trên.
powershell -NoProfile -Command "Start-Sleep -Seconds 5"
exit /b 0

:no_uv
echo  [Lỗi] Máy chưa có lệnh uv, là chương trình cài thư viện và chạy tool này.
echo  Cách cài: xem https://docs.astral.sh/uv/ rồi mở lại file run.bat.
pause
exit /b 1

:failed
echo.
echo  [Lỗi] Bước ở trên không chạy được nên tool chưa mở.
echo  Hãy chụp lại các dòng chữ phía trên để nhờ sửa.
pause
exit /b 1
