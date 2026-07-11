# Build NSHM OMR

## Windows x64 bằng GitHub Actions

1. Đưa toàn bộ project lên một repository GitHub riêng tư.
2. Mở tab **Actions** và chọn **Build NSHM OMR for Windows x64**.
3. Chọn **Run workflow**.
4. Khi workflow hoàn thành, tải artifact `NSHM-OMR-v1.0-windows-x64`.
5. Giải nén để nhận `NSHM OMR.exe`.

File EXE không yêu cầu cài Python. Dữ liệu được lưu tại
`%LOCALAPPDATA%\NSHM OMR\batches`.

## Build trực tiếp trên máy Windows

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller==6.19.0
python -m unittest tests.test_synthetic -v
pyinstaller --clean --noconfirm NSHM-OMR-Windows.spec
```

Đầu ra nằm tại `dist\NSHM OMR.exe`.
