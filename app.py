from __future__ import annotations

import os
import re
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, render_template, request, send_file

from omr import OMRProcessor
from omr.batch import BatchProcessor


BASE_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
if getattr(sys, "frozen", False):
    if sys.platform == "win32":
        DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "NSHM OMR"
    else:
        DATA_DIR = Path.home() / "Library" / "Application Support" / "NSHM OMR"
else:
    DATA_DIR = BASE_DIR / "tmp"
TEMPLATE_PATH = RESOURCE_DIR / "assets" / "template.png"

app = Flask(
    __name__,
    template_folder=str(RESOURCE_DIR / "templates"),
    static_folder=str(RESOURCE_DIR / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024
processor = OMRProcessor(TEMPLATE_PATH)
batch_processor = BatchProcessor(processor, DATA_DIR / "batches")


def parse_section1(raw: str) -> list[str]:
    answers = re.findall(r"[ABCD]", raw.upper())
    if len(answers) != 40:
        raise ValueError("Phan I can dung 40 dap an A/B/C/D.")
    return answers


def _normalize_tf_line(line: str) -> str:
    cleaned = re.sub(r"[^A-ZĐ0-9]", "", line.upper())
    cleaned = (
        cleaned.replace("Đ", "D")
        .replace("T", "D")
        .replace("1", "D")
        .replace("F", "S")
        .replace("0", "S")
    )
    if not re.fullmatch(r"[DS]{4}", cleaned):
        raise ValueError("Moi dong Phan II phai co 4 ky tu D hoac S.")
    return cleaned


def parse_section2(raw: str) -> list[list[str]]:
    lines = [line for line in (item.strip() for item in raw.splitlines()) if line]
    if len(lines) != 8:
        raise ValueError("Phan II can 8 dong, moi dong ung voi 1 cau.")
    return [list(_normalize_tf_line(line)) for line in lines]


def _normalize_short_answer(value: str) -> str:
    normalized = re.sub(r"\s+", "", value.strip())
    if len(normalized) > 4:
        raise ValueError("Phan III moi cau toi da 4 ky tu.")
    if normalized.count("-") > 1 or ("-" in normalized and not normalized.startswith("-")):
        raise ValueError("Dau tru trong Phan III chi duoc dat o vi tri dau tien.")
    if normalized.count(",") > 1:
        raise ValueError("Phan III chi duoc co toi da 1 dau phay.")
    if normalized and not re.fullmatch(r"-?(?:\d{0,3}(?:,\d)?|\d{1,4})", normalized):
        raise ValueError("Phan III chi nhan so, dau tru va dau phay.")
    return normalized


def parse_section3(raw: str) -> list[str]:
    lines = [line for line in (item.strip() for item in raw.splitlines()) if line]
    if len(lines) != 6:
        raise ValueError("Phan III can 6 dong, moi dong ung voi 1 cau.")
    return [_normalize_short_answer(line) for line in lines]


def parse_answer_key(form_data) -> dict[str, list]:
    return {
        "section1": parse_section1(form_data.get("section1", "")),
        "section2": parse_section2(form_data.get("section2", "")),
        "section3": parse_section3(form_data.get("section3", "")),
    }


def parse_answer_keys(form_data) -> dict[str, dict[str, list]]:
    codes = form_data.getlist("exam_code")
    section1_values = form_data.getlist("section1")
    section2_values = form_data.getlist("section2")
    section3_values = form_data.getlist("section3")
    if not codes:
        return {"default": parse_answer_key(form_data)}

    answer_keys: dict[str, dict[str, list]] = {}
    for index, raw_code in enumerate(codes):
        code = re.sub(r"\D", "", raw_code)
        if not code and not any(
            index < len(values) and values[index].strip()
            for values in (section1_values, section2_values, section3_values)
        ):
            continue
        if len(code) != 4:
            raise ValueError(f"Mã đề {index + 1} phải gồm đúng 4 chữ số.")
        if code in answer_keys:
            raise ValueError(f"Mã đề {code} đang bị nhập trùng.")
        try:
            answer_keys[code] = {
                "section1": parse_section1(section1_values[index]),
                "section2": parse_section2(section2_values[index]),
                "section3": parse_section3(section3_values[index]),
            }
        except (IndexError, ValueError) as error:
            raise ValueError(f"Mã đề {code}: {error}") from error
    if not answer_keys:
        raise ValueError("Cần nhập ít nhất một bộ đáp án.")
    return answer_keys


def build_ssl_context() -> Any:
    ssl_mode = os.environ.get("SSL_MODE", "").strip().lower()
    cert_file = os.environ.get("SSL_CERT_FILE", "").strip()
    key_file = os.environ.get("SSL_KEY_FILE", "").strip()

    if cert_file and key_file:
        return (cert_file, key_file)
    if ssl_mode == "adhoc":
        return "adhoc"
    return None


@app.get("/")
def index():
    defaults = {
        "section1": "A B C D A B C D A B C D A B C D A B C D A B C D A B C D A B C D A B C D A B C D",
        "section2": "DSDS\nSDDS\nDDSS\nSSDD\nDSDD\nSDSS\nDDDS\nSSSD",
        "section3": "123\n456\n789\n-12\n305\n999",
    }
    exam_keys = [
        {"code": code, **defaults}
        for code in ("0101", "0102", "0103", "0104")
    ]
    return render_template(
        "index.html",
        values=defaults,
        exam_keys=exam_keys,
        error=None,
        sheet_ratio=round(processor.template.width / processor.template.height, 5),
    )


@app.post("/grade")
def grade():
    values = {
        "section1": request.form.get("section1", ""),
        "section2": request.form.get("section2", ""),
        "section3": request.form.get("section3", ""),
    }
    upload = request.files.get("sheet")

    if upload is None or not upload.filename:
        return render_template("index.html", values=values, error="Can chon anh phieu tra loi de cham.")

    try:
        answer_key = parse_answer_key(request.form)
        result = processor.grade(upload.read(), answer_key)
    except ValueError as error:
        return render_template(
            "index.html",
            values=values,
            error=str(error),
            sheet_ratio=round(processor.template.width / processor.template.height, 5),
        )

    return render_template("result.html", result=result, values=values)


@app.post("/batch/grade")
def batch_grade():
    upload = request.files.get("batch_pdf")
    values = {
        "section1": request.form.get("section1", ""),
        "section2": request.form.get("section2", ""),
        "section3": request.form.get("section3", ""),
    }
    codes = request.form.getlist("exam_code")
    section1_values = request.form.getlist("section1")
    section2_values = request.form.getlist("section2")
    section3_values = request.form.getlist("section3")
    exam_keys = [
        {
            "code": code,
            "section1": section1_values[index] if index < len(section1_values) else "",
            "section2": section2_values[index] if index < len(section2_values) else "",
            "section3": section3_values[index] if index < len(section3_values) else "",
        }
        for index, code in enumerate(codes)
    ]
    if upload is None or not upload.filename:
        return render_template(
            "index.html",
            values=values,
            exam_keys=exam_keys,
            error="Hãy chọn file PDF CamScanner cần chấm.",
            sheet_ratio=round(processor.template.width / processor.template.height, 5),
        )
    if not upload.filename.lower().endswith(".pdf"):
        return render_template(
            "index.html",
            values=values,
            exam_keys=exam_keys,
            error="Chế độ chấm cả lớp chỉ nhận file PDF.",
            sheet_ratio=round(processor.template.width / processor.template.height, 5),
        )
    try:
        answer_keys = parse_answer_keys(request.form)
        batch = batch_processor.process_pdf(upload.read(), answer_keys, filename=upload.filename)
    except ValueError as error:
        return render_template(
            "index.html",
            values=values,
            exam_keys=exam_keys,
            error=str(error),
            sheet_ratio=round(processor.template.width / processor.template.height, 5),
        )
    return render_template("batch_result.html", batch=batch)


@app.get("/batch/<batch_id>")
def batch_result(batch_id: str):
    try:
        batch = batch_processor.load(batch_id)
    except FileNotFoundError:
        abort(404)
    return render_template("batch_result.html", batch=batch)


@app.get("/batch/<batch_id>/asset/<filename>")
def batch_asset(batch_id: str, filename: str):
    try:
        path = batch_processor.asset_path(batch_id, filename)
    except FileNotFoundError:
        abort(404)
    return send_file(path)


@app.get("/batch/<batch_id>/export.xlsx")
def batch_export_binary(batch_id: str):
    try:
        data = batch_processor.export_binary_xlsx(batch_id)
    except FileNotFoundError:
        abort(404)
    return send_file(
        BytesIO(data),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"summary-{batch_id}.xlsx",
    )


@app.post("/api/preview")
def api_preview():
    frame = request.files.get("frame")
    if frame is None or not frame.filename:
        return jsonify({"error": "Can gui frame preview tu camera."}), 400

    try:
        preview = processor.preview(frame.read())
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(preview)


@app.post("/api/grade")
def api_grade():
    frame = request.files.get("frame")
    if frame is None or not frame.filename:
        return jsonify({"error": "Can gui frame chup tu camera."}), 400

    try:
        answer_key = parse_answer_key(request.form)
        result = processor.grade(frame.read(), answer_key)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(result)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5050"))
    ssl_context = build_ssl_context()
    app.run(debug=True, host=host, port=port, ssl_context=ssl_context)
