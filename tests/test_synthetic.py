from __future__ import annotations

from io import BytesIO
import unittest
from pathlib import Path
import sys

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from omr import OMRProcessor
from app import app

TEMPLATE_PATH = BASE_DIR / "assets" / "template.png"


def render_answered_template(
    processor: OMRProcessor,
    answer_key: dict[str, list[str]],
) -> np.ndarray:
    image = cv2.imread(str(TEMPLATE_PATH), cv2.IMREAD_COLOR)
    assert image is not None

    student_id = "12345678"
    exam_code = "1234"

    for digit, column in zip(student_id, processor.template.student_id):
        bubble = column[digit]
        cv2.circle(image, tuple(int(round(v)) for v in bubble.center), int(bubble.radius * 0.55), (0, 0, 0), -1)

    for digit, column in zip(exam_code, processor.template.exam_code):
        bubble = column[digit]
        cv2.circle(image, tuple(int(round(v)) for v in bubble.center), int(bubble.radius * 0.55), (0, 0, 0), -1)

    for expected, question in zip(answer_key["section1"], processor.template.section1):
        bubble = question[expected]
        cv2.circle(image, tuple(int(round(v)) for v in bubble.center), int(bubble.radius * 0.55), (0, 0, 0), -1)

    for answers, question in zip(answer_key["section2"], processor.template.section2):
        for statement, expected in zip("abcd", answers):
            bubble = question[statement][expected]
            cv2.circle(image, tuple(int(round(v)) for v in bubble.center), int(bubble.radius * 0.55), (0, 0, 0), -1)

    for expected, question in zip(answer_key["section3"], processor.template.section3):
        for index, char in enumerate(expected):
            bubble = question[index][char]
            cv2.circle(image, tuple(int(round(v)) for v in bubble.center), int(bubble.radius * 0.55), (0, 0, 0), -1)
    return image


def render_synthetic_sheet(
    processor: OMRProcessor,
    answer_key: dict[str, list[str]],
    *,
    with_lighting_noise: bool = False,
) -> bytes:
    image = render_answered_template(processor, answer_key)

    height, width = image.shape[:2]
    source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    target = np.float32([[48, 32], [width - 62, 18], [width - 15, height - 40], [20, height - 12]])
    matrix = cv2.getPerspectiveTransform(source, target)
    warped = cv2.warpPerspective(image, matrix, (width, height), borderValue=(255, 255, 255))
    blurred = cv2.GaussianBlur(warped, (3, 3), 0)
    if with_lighting_noise:
        x_gradient = np.linspace(0.78, 1.08, width, dtype=np.float32)
        y_gradient = np.linspace(1.06, 0.92, height, dtype=np.float32)[:, None]
        lighting = y_gradient * x_gradient[None, :]
        noisy = blurred.astype(np.float32) * lighting[..., None]
        rng = np.random.default_rng(42)
        noisy += rng.normal(0.0, 5.5, noisy.shape)
        blurred = np.clip(noisy, 0, 255).astype(np.uint8)
    encoded, data = cv2.imencode(".png", blurred)
    assert encoded
    return data.tobytes()


def render_synthetic_photo_sheet(processor: OMRProcessor, answer_key: dict[str, list[str]]) -> bytes:
    page = render_answered_template(processor, answer_key)
    page_height, page_width = page.shape[:2]

    canvas_height = page_height + 620
    canvas_width = page_width + 520
    x_gradient = np.linspace(0.92, 0.78, canvas_width, dtype=np.float32)
    y_gradient = np.linspace(0.88, 1.0, canvas_height, dtype=np.float32)[:, None]
    base = 228.0 * (x_gradient[None, :] * y_gradient)
    canvas = np.clip(np.dstack([base * 0.99, base * 0.97, base * 0.93]), 0, 255).astype(np.uint8)

    source = np.float32([[0, 0], [page_width - 1, 0], [page_width - 1, page_height - 1], [0, page_height - 1]])
    target = np.float32(
        [
            [185, 125],
            [canvas_width - 140, 58],
            [canvas_width - 66, canvas_height - 120],
            [114, canvas_height - 32],
        ]
    )
    matrix = cv2.getPerspectiveTransform(source, target)
    warped = cv2.warpPerspective(page, matrix, (canvas_width, canvas_height), borderValue=(255, 255, 255))

    page_mask = np.zeros((canvas_height, canvas_width), dtype=np.uint8)
    cv2.fillConvexPoly(page_mask, np.round(target).astype(np.int32), 255)
    canvas[page_mask > 0] = warped[page_mask > 0]

    shadow = cv2.GaussianBlur(page_mask, (0, 0), sigmaX=18, sigmaY=18)
    shadow = (shadow.astype(np.float32) / 255.0) * 28.0
    shadow = np.dstack([shadow, shadow, shadow]).astype(np.float32)
    photo = np.clip(canvas.astype(np.float32) - shadow, 0, 255).astype(np.uint8)

    rng = np.random.default_rng(7)
    photo = np.clip(photo.astype(np.float32) + rng.normal(0.0, 4.0, photo.shape), 0, 255).astype(np.uint8)
    photo = cv2.GaussianBlur(photo, (3, 3), 0)

    encoded, data = cv2.imencode(".png", photo)
    assert encoded
    return data.tobytes()


class SyntheticOMRTest(unittest.TestCase):
    def _answer_key(self) -> dict[str, list[str]]:
        return {
            "section1": list("ABCDABCDABCDABCDABCDABCDABCDABCDABCDABCD"),
            "section2": [list(item) for item in ("DSDS", "SDDS", "DDSS", "SSDD", "DSDD", "SDSS", "DDDS", "SSSD")],
            "section3": ["123", "456", "789", "-12", "305", "999"],
        }

    def test_grade_synthetic_sheet(self) -> None:
        processor = OMRProcessor(TEMPLATE_PATH)
        answer_key = self._answer_key()

        synthetic_image = render_synthetic_sheet(processor, answer_key)
        result = processor.grade(synthetic_image, answer_key)

        self.assertEqual(result["student_id"], "12345678")
        self.assertEqual(result["exam_code"], "1234")
        self.assertEqual(result["totals"]["section1"]["correct"], 40)
        self.assertEqual(result["totals"]["section2"]["correct"], 32)
        self.assertEqual(result["totals"]["section3"]["correct"], 6)
        self.assertEqual(result["totals"]["overall"]["correct"], 78)

    def test_grade_synthetic_sheet_with_lighting_noise(self) -> None:
        processor = OMRProcessor(TEMPLATE_PATH)
        answer_key = self._answer_key()

        synthetic_image = render_synthetic_sheet(processor, answer_key, with_lighting_noise=True)
        result = processor.grade(synthetic_image, answer_key)

        self.assertEqual(result["student_id"], "12345678")
        self.assertEqual(result["exam_code"], "1234")
        self.assertEqual(result["totals"]["section1"]["correct"], 40)
        self.assertEqual(result["totals"]["section2"]["correct"], 32)
        self.assertEqual(result["totals"]["section3"]["correct"], 6)

    def test_grade_synthetic_photo_sheet(self) -> None:
        processor = OMRProcessor(TEMPLATE_PATH)
        answer_key = self._answer_key()

        synthetic_image = render_synthetic_photo_sheet(processor, answer_key)
        result = processor.grade(synthetic_image, answer_key)

        self.assertEqual(result["student_id"], "12345678")
        self.assertEqual(result["exam_code"], "1234")
        self.assertEqual(result["totals"]["section1"]["correct"], 40)
        self.assertEqual(result["totals"]["section2"]["correct"], 32)
        self.assertEqual(result["totals"]["section3"]["correct"], 6)

    def test_preview_detects_synthetic_photo_sheet(self) -> None:
        processor = OMRProcessor(TEMPLATE_PATH)
        answer_key = self._answer_key()

        synthetic_image = render_synthetic_photo_sheet(processor, answer_key)
        preview = processor.preview(synthetic_image)

        self.assertTrue(preview["detected"])
        self.assertEqual(len(preview["corners"]), 4)
        self.assertGreater(preview["metrics"]["coverage"], 0.4)

    def test_camera_api_preview_and_grade(self) -> None:
        answer_key = self._answer_key()
        processor = OMRProcessor(TEMPLATE_PATH)
        synthetic_image = render_synthetic_photo_sheet(processor, answer_key)

        with app.test_client() as client:
            preview_response = client.post(
                "/api/preview",
                data={"frame": (BytesIO(synthetic_image), "frame.png")},
                content_type="multipart/form-data",
            )
            self.assertEqual(preview_response.status_code, 200)
            preview_payload = preview_response.get_json()
            assert preview_payload is not None
            self.assertTrue(preview_payload["detected"])

            grade_response = client.post(
                "/api/grade",
                data={
                    "section1": " ".join(answer_key["section1"]),
                    "section2": "\n".join("".join(item) for item in answer_key["section2"]),
                    "section3": "\n".join(answer_key["section3"]),
                    "frame": (BytesIO(synthetic_image), "frame.png"),
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(grade_response.status_code, 200)
            grade_payload = grade_response.get_json()
            assert grade_payload is not None
            self.assertEqual(grade_payload["student_id"], "12345678")
            self.assertEqual(grade_payload["exam_code"], "1234")


if __name__ == "__main__":
    unittest.main()
