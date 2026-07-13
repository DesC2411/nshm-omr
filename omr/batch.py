from __future__ import annotations

import base64
import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.sax.saxutils import escape

import fitz

from .processor import OMRProcessor


class BatchProcessor:
    def __init__(self, processor: OMRProcessor, storage_root: str | Path):
        self.processor = processor
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def process_pdf(
        self,
        pdf_bytes: bytes,
        answer_keys: dict[str, dict[str, Any]],
        *,
        filename: str,
    ) -> dict[str, Any]:
        try:
            document = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as error:
            raise ValueError("Khong doc duoc file PDF.") from error
        if not 1 <= document.page_count <= 300:
            raise ValueError("Moi file PDF can co tu 1 den 300 trang.")

        batch_id = uuid4().hex[:16]
        batch_dir = self.storage_root / batch_id
        batch_dir.mkdir(parents=True, exist_ok=False)
        pages: list[dict[str, Any]] = []
        matrix = fitz.Matrix(150 / 72.0, 150 / 72.0)

        fallback_key = next(iter(answer_keys.values()))
        for page_index, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
            image_bytes = pixmap.tobytes("jpeg", jpg_quality=92)
            original_name = f"page-{page_index:03d}.jpg"
            (batch_dir / original_name).write_bytes(image_bytes)

            try:
                result = self.processor.grade(image_bytes, fallback_key)
                matched_key = answer_keys.get(result["exam_code"])
                if matched_key is not None and matched_key is not fallback_key:
                    result = self.processor.grade(image_bytes, matched_key)
                missing_key = result["exam_code"] not in answer_keys
                if missing_key:
                    result["review_reasons"].append(
                        f"Không có đáp án cho mã đề {result['exam_code']}"
                    )
                    result["needs_review"] = True
                overlay_name = f"overlay-{page_index:03d}.png"
                (batch_dir / overlay_name).write_bytes(base64.b64decode(result.pop("overlay_base64")))
                page_result = self._compact_result(result)
                page_result.update(
                    {
                        "page": page_index,
                        "status": "review" if result["needs_review"] else "accepted",
                        "original_image": original_name,
                        "overlay_image": overlay_name,
                        "error": None,
                    }
                )
            except ValueError as error:
                page_result = {
                    "page": page_index,
                    "status": "rejected",
                    "student_id": "?",
                    "exam_code": "?",
                    "score_10": None,
                    "quality": {"status": "rejected", "score": 0},
                    "review_reasons": [str(error)],
                    "original_image": original_name,
                    "overlay_image": None,
                    "error": str(error),
                    "section1_answers": "",
                    "section2_answers": "",
                    "section3_answers": "",
                    "totals": {},
                    "sections": {"section1": [], "section2": [], "section3": []},
                }
            pages.append(page_result)

        batch = {
            "id": batch_id,
            "filename": filename,
            "page_count": len(pages),
            "accepted_count": sum(page["status"] == "accepted" for page in pages),
            "review_count": sum(page["status"] == "review" for page in pages),
            "rejected_count": sum(page["status"] == "rejected" for page in pages),
            "exam_codes": list(answer_keys),
            "pages": pages,
        }
        (batch_dir / "results.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
        return batch

    def load(self, batch_id: str) -> dict[str, Any]:
        path = self._batch_dir(batch_id) / "results.json"
        if not path.exists():
            raise FileNotFoundError(batch_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def asset_path(self, batch_id: str, filename: str) -> Path:
        batch_dir = self._batch_dir(batch_id)
        path = (batch_dir / filename).resolve()
        if path.parent != batch_dir.resolve() or not path.is_file():
            raise FileNotFoundError(filename)
        return path

    def export_csv(self, batch_id: str) -> bytes:
        batch = self.load(batch_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Trang",
                "Trạng thái",
                "Mã học sinh",
                "Mã đề",
                "Điểm",
                "Phần I",
                "Phần II",
                "Phần III",
                "Lý do cần kiểm tra",
            ]
        )
        for page in batch["pages"]:
            writer.writerow(
                [
                    page["page"],
                    page["status"],
                    page["student_id"],
                    page["exam_code"],
                    "" if page["score_10"] is None else page["score_10"],
                    page["section1_answers"],
                    page["section2_answers"],
                    page["section3_answers"],
                    "; ".join(page["review_reasons"]),
                ]
            )
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    def export_binary_xlsx(self, batch_id: str) -> bytes:
        batch = self.load(batch_id)
        headers = self._binary_headers()
        rows: list[list[Any]] = []
        for page in batch["pages"]:
            sections = page["sections"]
            binary = [int(item.get("correct", False)) for item in sections["section1"]]
            binary += [int(item.get("correct", False)) for item in sections["section2"]]
            binary += [int(item.get("correct", False)) for item in sections["section3"]]
            binary += [""] * (78 - len(binary))
            totals = page.get("totals") or {}
            part1 = totals.get("section1") or {}
            part2 = totals.get("section2") or {}
            part3 = totals.get("section3") or {}
            overall = totals.get("overall") or {}
            status = {"accepted": "ok", "review": "review", "rejected": "error"}.get(
                page["status"], page["status"]
            )
            rows.append(
                [
                    status,
                    "; ".join(page.get("review_reasons") or []),
                    batch["filename"],
                    batch["filename"],
                    page["page"],
                    f"Trang {page['page']}",
                    f"{batch_id}/page_{page['page']:04d}",
                    f"{batch_id}/results.json",
                    page["student_id"],
                    page["exam_code"],
                    *binary[:78],
                    part1.get("correct", ""),
                    part1.get("total", ""),
                    part2.get("correct", ""),
                    part2.get("total", ""),
                    part3.get("correct", ""),
                    part3.get("total", ""),
                    overall.get("correct", ""),
                    overall.get("total", ""),
                ]
            )
        return self._write_xlsx(headers, rows)

    @staticmethod
    def _binary_headers() -> list[str]:
        headers = [
            "status", "error", "file_name", "file_path", "page_number",
            "page_label", "output_dir", "results_json", "sbd", "exam_code",
        ]
        headers += [f"part1_{question}" for question in range(1, 41)]
        headers += [
            f"part2_{question}{statement}"
            for question in range(1, 9)
            for statement in "abcd"
        ]
        headers += [f"part3_{question}" for question in range(1, 7)]
        headers += [
            "part1_score", "part1_max_score", "part2_score", "part2_max_score",
            "part3_score", "part3_max_score", "total_score", "max_score",
        ]
        return headers

    @classmethod
    def _write_xlsx(cls, headers: list[str], rows: list[list[Any]]) -> bytes:
        sheet_rows = [headers, *rows]
        last_column = cls._xlsx_column_name(len(headers))
        row_xml: list[str] = []
        for row_number, values in enumerate(sheet_rows, start=1):
            cells = [
                cls._xlsx_cell_xml(
                    row_number,
                    column_number,
                    value,
                    style_index=1 if row_number == 1 else 0,
                )
                for column_number, value in enumerate(values, start=1)
            ]
            row_xml.append(f'<row r="{row_number}">{"".join(filter(None, cells))}</row>')

        sheet_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<dimension ref="A1:{last_column}{max(len(sheet_rows), 1)}"/>'
            '<sheetViews><sheetView workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
            '</sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/>'
            f'<sheetData>{"".join(row_xml)}</sheetData>'
            f'<autoFilter ref="A1:{last_column}{max(len(sheet_rows), 1)}"/>'
            '</worksheet>'
        )
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", cls._xlsx_content_types())
            archive.writestr("_rels/.rels", cls._xlsx_root_rels())
            archive.writestr("docProps/app.xml", cls._xlsx_app_props())
            archive.writestr("docProps/core.xml", cls._xlsx_core_props(created_at))
            archive.writestr("xl/workbook.xml", cls._xlsx_workbook())
            archive.writestr("xl/_rels/workbook.xml.rels", cls._xlsx_workbook_rels())
            archive.writestr("xl/styles.xml", cls._xlsx_styles())
            archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        return output.getvalue()

    @staticmethod
    def _xlsx_column_name(column_number: int) -> str:
        name = ""
        while column_number:
            column_number, remainder = divmod(column_number - 1, 26)
            name = chr(65 + remainder) + name
        return name

    @classmethod
    def _xlsx_cell_xml(
        cls, row_number: int, column_number: int, value: Any, style_index: int = 0
    ) -> str:
        if value is None or value == "":
            return ""
        cell_ref = f"{cls._xlsx_column_name(column_number)}{row_number}"
        style = f' s="{style_index}"' if style_index else ""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f'<c r="{cell_ref}"{style}><v>{value}</v></c>'
        safe_text = escape(str(value))
        return (
            f'<c r="{cell_ref}" t="inlineStr"{style}>'
            f'<is><t xml:space="preserve">{safe_text}</t></is></c>'
        )

    @staticmethod
    def _xlsx_content_types() -> str:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>'''

    @staticmethod
    def _xlsx_root_rels() -> str:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''

    @staticmethod
    def _xlsx_app_props() -> str:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>NSHM OMR</Application></Properties>'''

    @staticmethod
    def _xlsx_core_props(created_at: str) -> str:
        return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:creator>NSHM OMR</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">{created_at}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{created_at}</dcterms:modified></cp:coreProperties>'''

    @staticmethod
    def _xlsx_workbook() -> str:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Summary" sheetId="1" r:id="rId1"/></sheets></workbook>'''

    @staticmethod
    def _xlsx_workbook_rels() -> str:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''

    @staticmethod
    def _xlsx_styles() -> str:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''

    def _batch_dir(self, batch_id: str) -> Path:
        if not batch_id.isalnum():
            raise FileNotFoundError(batch_id)
        return self.storage_root / batch_id

    @staticmethod
    def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
        def clean(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                {key: value for key, value in item.items() if key not in {"bubbles", "columns"}}
                for item in items
            ]

        section1 = clean(result["section1"])
        section2 = clean(result["section2"])
        section3 = clean(result["section3"])
        section1_answers = "".join(item["selected"] if item["selected"] != "-" else "-" for item in section1)
        section2_answers = " / ".join(
            "".join(
                next(
                    (
                        item["selected"] if item["selected"] != "-" else "-"
                        for item in section2
                        if item["question"] == question and item["statement"] == statement
                    ),
                    "-",
                )
                for statement in "abcd"
            )
            for question in range(1, 9)
        )
        section3_answers = " / ".join(item["selected"] for item in section3)
        return {
            "student_id": result["student_id"],
            "student_id_status": result["student_id_status"],
            "exam_code": result["exam_code"],
            "exam_code_status": result["exam_code_status"],
            "score_10": result["totals"]["score_10"],
            "totals": result["totals"],
            "quality": result["quality"],
            "calibration": result["calibration"],
            "review_reasons": result["review_reasons"],
            "section1_answers": section1_answers,
            "section2_answers": section2_answers,
            "section3_answers": section3_answers,
            "sections": {"section1": section1, "section2": section2, "section3": section3},
        }
