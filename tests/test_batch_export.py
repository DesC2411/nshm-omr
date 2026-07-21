from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from omr.batch import BatchProcessor


class BatchExportTest(unittest.TestCase):
    def test_configurable_score_rules(self) -> None:
        page = {
            "status": "accepted",
            "review_reasons": [],
            "sections": {
                "section1": [{"correct": True}, {"correct": True}, {"correct": False}],
                "section2": [
                    *[{"question": 1, "correct": index == 0} for index in range(4)],
                    *[{"question": 2, "correct": index < 3} for index in range(4)],
                ],
                "section3": [{"correct": True}, {"correct": False}],
            },
        }
        config = {
            "section1_per_correct": 0.25,
            "section2_by_correct": {"1": 0.1, "2": 0.25, "3": 0.5, "4": 1.0},
            "section3_per_correct": 0.5,
        }

        score = BatchProcessor.calculate_page_score(page, config)

        assert score is not None
        self.assertEqual(score["section1"], 0.5)
        self.assertEqual(score["section2"], 0.6)
        self.assertEqual(score["section3"], 0.5)
        self.assertEqual(score["total"], 1.6)
        self.assertEqual(score["max_score"], 3.75)
        self.assertEqual(
            [(item["correct"], item["score"]) for item in score["section2_questions"]],
            [(1, 0.1), (3, 0.5)],
        )

    def test_binary_export_matches_summary_xlsx_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            storage = Path(temporary_dir)
            batch_id = "testbatch01"
            batch_dir = storage / batch_id
            batch_dir.mkdir()
            section1 = [{"correct": index % 2 == 0} for index in range(20)]
            section2 = [{"correct": index % 3 == 0} for index in range(16)]
            section3 = [{"correct": index < 2} for index in range(3)]
            batch = {
                "id": batch_id,
                "filename": "lop-10a1.pdf",
                "pages": [
                    {
                        "page": 1,
                        "status": "accepted",
                        "student_id": "00000117",
                        "exam_code": "0101",
                        "review_reasons": [],
                        "sections": {
                            "section1": section1,
                            "section2": section2,
                            "section3": section3,
                        },
                        "totals": {
                            "section1": {"correct": 10, "total": 20},
                            "section2": {"correct": 6, "total": 16},
                            "section3": {"correct": 2, "total": 3},
                            "overall": {"correct": 18, "total": 39},
                        },
                    }
                ],
            }
            (batch_dir / "results.json").write_text(json.dumps(batch), encoding="utf-8")
            exporter = BatchProcessor.__new__(BatchProcessor)
            exporter.storage_root = storage

            data = exporter.export_binary_xlsx(batch_id)
            self.assertTrue(data.startswith(b"PK\x03\x04"))
            with zipfile.ZipFile(BytesIO(data)) as archive:
                sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
                workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))

            namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            self.assertEqual(workbook.find("m:sheets/m:sheet", namespace).attrib["name"], "Summary")
            self.assertEqual(sheet.find("m:dimension", namespace).attrib["ref"], "A1:CR2")
            self.assertEqual(sheet.find("m:autoFilter", namespace).attrib["ref"], "A1:CR2")
            headers = [
                cell.find("m:is/m:t", namespace).text
                for cell in sheet.findall(".//m:sheetData/m:row", namespace)[0]
            ]
            self.assertEqual(len(headers), 96)
            self.assertEqual(headers[:10], BatchProcessor._binary_headers()[:10])
            self.assertEqual(headers[-8:], [
                "part1_score", "part1_max_score", "part2_score", "part2_max_score",
                "part3_score", "part3_max_score", "total_score", "max_score",
            ])
            data_cells = {
                cell.attrib["r"]: cell.find("m:v", namespace).text
                for cell in sheet.findall(".//m:sheetData/m:row", namespace)[1]
                if cell.find("m:v", namespace) is not None
            }
            self.assertNotIn("AE2", data_cells)  # Phần I câu 21 không sử dụng.
            self.assertEqual(data_cells["AY2"], "1")  # Phần II câu 1a vẫn đúng cột.
            self.assertEqual(data_cells["CE2"], "1")  # Phần III câu 1 vẫn đúng cột.


if __name__ == "__main__":
    unittest.main()
