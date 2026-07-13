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
    def test_binary_export_matches_summary_xlsx_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            storage = Path(temporary_dir)
            batch_id = "testbatch01"
            batch_dir = storage / batch_id
            batch_dir.mkdir()
            section1 = [{"correct": index % 2 == 0} for index in range(40)]
            section2 = [{"correct": index % 3 == 0} for index in range(32)]
            section3 = [{"correct": index < 2} for index in range(6)]
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
                            "section1": {"correct": 20, "total": 40},
                            "section2": {"correct": 11, "total": 32},
                            "section3": {"correct": 2, "total": 6},
                            "overall": {"correct": 33, "total": 78},
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


if __name__ == "__main__":
    unittest.main()
