from __future__ import annotations

import base64
import csv
import io
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

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

    def export_binary_csv(self, batch_id: str) -> bytes:
        batch = self.load(batch_id)
        output = io.StringIO()
        writer = csv.writer(output)
        headers = ["STT", "SBD", "Mã đề", "Điểm", "Trạng thái"]
        headers += [f"I.{question}" for question in range(1, 41)]
        headers += [f"II.{question}{statement}" for question in range(1, 9) for statement in "abcd"]
        headers += [f"III.{question}" for question in range(1, 7)]
        writer.writerow(headers)
        for page in batch["pages"]:
            sections = page["sections"]
            binary = [int(item.get("correct", False)) for item in sections["section1"]]
            binary += [int(item.get("correct", False)) for item in sections["section2"]]
            binary += [int(item.get("correct", False)) for item in sections["section3"]]
            writer.writerow(
                [page["page"], page["student_id"], page["exam_code"],
                 "" if page["score_10"] is None else page["score_10"], page["status"], *binary]
            )
        return ("\ufeff" + output.getvalue()).encode("utf-8")

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
