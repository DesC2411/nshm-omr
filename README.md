# NSHM OMR v1.0

Ứng dụng chấm phiếu trắc nghiệm tự động dành cho quy trình nội bộ tại trường học. Giáo viên quét nhiều bài bằng CamScanner, nhập một file PDF nhiều trang và nhận kết quả, ảnh overlay cùng bảng tổng hợp ngay trên máy tính.

> Phiên bản hiện tại sử dụng một mẫu phiếu NSHM cố định và hoạt động hoàn toàn cục bộ, không tải bài thi lên dịch vụ bên ngoài.

## Tính năng

- Nhận PDF CamScanner từ 1 đến 300 trang.
- Kiểm tra bốn mốc góc trước khi nhận dạng.
- Trải phẳng ảnh bằng biến đổi phối cảnh.
- Chuẩn hóa và đánh giá ánh sáng, độ nét, sai số căn chỉnh.
- Đọc mã học sinh 8 chữ số và mã đề 4 chữ số.
- Hỗ trợ nhiều mã đề, hiển thị sẵn 4 mã và có thể thêm mã mới.
- Chấm Phần I gồm 40 câu A/B/C/D.
- Chấm Phần II gồm 8 câu đúng/sai, mỗi câu 4 ý.
- Chấm Phần III gồm 6 câu trả lời ngắn dạng số.
- Đánh dấu đáp án học sinh và đáp án đúng trên overlay.
- Không tự đoán khi mã, đáp án hoặc chất lượng ảnh chưa chắc chắn.
- Lọc các bài đạt, cần xem lại và bị từ chối.
- Xuất workbook Excel `.xlsx` theo đúng bảng `0/1` từng ý.
- Chỉ nhập số câu thực tế của đề: tối đa 40 câu Phần I, 8 câu Phần II và 6 câu Phần III.
- Review và tính lại điểm theo thang điểm giáo viên cấu hình, không cần quét lại bài.

## Quy trình sử dụng

### 1. Chuẩn bị bài thi

1. Dùng CamScanner quét các phiếu theo chiều dọc.
2. Mỗi trang chỉ chứa một phiếu.
3. Đảm bảo nhìn thấy đủ bốn mốc vuông đen ở bốn góc.
4. Hạn chế bóng đổ, nếp gấp, mất góc hoặc trang quá mờ.
5. Xuất toàn bộ bài thành một PDF nhiều trang.

### 2. Nhập dữ liệu

1. Mở NSHM OMR.
2. Chọn hoặc kéo PDF vào vùng **PDF bài làm**.
3. Nhập mã đề bằng đúng 4 chữ số, ví dụ `0101`.
4. Nhập đáp án cho cả ba phần của từng mã đề.
5. Dùng **+ Thêm mã đề** nếu kỳ thi có nhiều hơn 4 mã.
6. Bấm **Chấm toàn bộ PDF**.

### 3. Kiểm tra kết quả

- **Đạt kiểm tra**: hệ thống nhận đủ dữ liệu và chất lượng ảnh nằm trong ngưỡng an toàn.
- **Cần xem lại**: có mã hoặc ô tô chưa chắc chắn, hoặc sai số căn chỉnh cao.
- **Bị từ chối**: không đủ điều kiện để trải phẳng và nhận dạng an toàn.

Mỗi bài có thể mở ảnh gốc và overlay kích thước lớn để giáo viên đối chiếu.

### 4. Xuất dữ liệu

- **Xuất Excel 0/1**: mỗi bài là một dòng; đúng là `1`, sai hoặc bỏ trống là `0`. File có sheet `Summary`, 96 cột riêng biệt và không dùng CSV.

### 5. Review điểm

- Phần I và Phần III: đặt điểm cho mỗi câu đúng.
- Phần II: đặt riêng mức điểm khi đúng 1, 2, 3 hoặc 4 ý trong một câu.
- Mở **Review điểm** tại trang kết quả, kiểm tra bảng xem trước rồi chọn **Lưu và tính lại**.
- Sau khi lưu, các cột điểm trong file Excel sử dụng thang điểm đã cấu hình.

Bảng `0/1` gồm 78 ý: 40 câu Phần I, 32 ý Phần II và 6 câu Phần III.

## Sử dụng bản đóng gói

### macOS Apple Silicon

1. Tải file `NSHM-OMR-v1.0-mac-arm64.zip`.
2. Giải nén và kéo `NSHM OMR.app` vào Applications.
3. Lần mở đầu tiên, nhấp chuột phải vào ứng dụng, chọn **Open** và xác nhận.
4. Ứng dụng tự mở trình duyệt tại `http://127.0.0.1:5050`.

Bản arm64 hỗ trợ Mac M1, M2, M3, M4 và không hỗ trợ Mac Intel.

### Windows x64

1. Tải artifact `NSHM-OMR-v1.0-windows-x64` từ GitHub Actions.
2. Giải nén file ZIP.
3. Mở `NSHM OMR.exe`.
4. Nếu Windows SmartScreen cảnh báo bản chưa ký, chọn **More info** rồi **Run anyway**.
5. Ứng dụng tự mở trình duyệt tại `http://127.0.0.1:5050`.

Ứng dụng đóng gói không yêu cầu cài Python và không yêu cầu Internet khi chấm bài.

## Chạy từ mã nguồn

Yêu cầu Python 3.10 trở lên.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Trên Windows, kích hoạt môi trường bằng:

```powershell
.\.venv\Scripts\Activate.ps1
```

Sau đó mở [http://127.0.0.1:5050](http://127.0.0.1:5050).

## Tạo bản Windows bằng GitHub Actions

1. Mở tab **Actions** trong repository.
2. Chọn workflow **Build NSHM OMR for Windows x64**.
3. Chọn **Run workflow**.
4. Chờ bước test, build và smoke test hoàn tất.
5. Tải artifact ở cuối trang workflow.

Workflow chỉ phát hành ZIP khi test OMR và kiểm tra khởi động EXE đều thành công.

## Nơi lưu dữ liệu

- macOS: `~/Library/Application Support/NSHM OMR/batches`
- Windows: `%LOCALAPPDATA%\NSHM OMR\batches`
- Chạy từ mã nguồn: `tmp/batches`

Các thư mục kết quả không được đưa lên GitHub.

## Kiểm thử

```bash
python -m unittest tests.test_synthetic -v
```

Bộ test hiện kiểm tra ảnh chuẩn, nhiễu ánh sáng, ảnh chụp méo phối cảnh, API preview và API chấm bài.

## Cấu trúc chính

```text
omr/                      Bộ xử lý OMR
assets/template.png       Template phiếu cố định
templates/                Giao diện HTML
static/                   CSS, JavaScript và logo
tests/                    Kiểm thử tự động
desktop_launcher.py       Launcher cho ứng dụng đóng gói
NSHM-OMR.spec             Build macOS
NSHM-OMR-Windows.spec     Build Windows x64
.github/workflows/        GitHub Actions
```

## Bản quyền

Copyright © Nguyễn Trường Chinh.

- Facebook: [Nguyễn Trường Chinh](https://www.facebook.com/desc2411)
- Email: [truongchinh2k3@gmail.com](mailto:truongchinh2k3@gmail.com)
