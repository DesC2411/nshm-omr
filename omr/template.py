from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


CANONICAL_WIDTH = 1240
CANONICAL_HEIGHT = 1755
BUBBLE_RADIUS = 8.5

CORNER_MARKERS = {
    "top_left": (92.0, 40.5),
    "top_right": (1153.0, 34.0),
    "bottom_right": (1151.0, 1614.5),
    "bottom_left": (89.5, 1616.5),
}

GUIDE_MARKERS = [
    (92.0, 40.5),
    (1153.0, 34.0),
    (89.5, 544.0),
    (1152.5, 543.0),
    (89.0, 907.0),
    (1153.0, 905.0),
    (89.0, 1140.0),
    (1153.0, 1137.0),
    (89.5, 1616.5),
    (1151.0, 1614.5),
]


@dataclass(frozen=True)
class Bubble:
    center: tuple[float, float]
    radius: float = BUBBLE_RADIUS


@dataclass(frozen=True)
class TemplateLayout:
    width: int
    height: int
    marker_centers: dict[str, tuple[float, float]]
    guide_markers: list[tuple[float, float]]
    student_id: list[dict[str, Bubble]]
    exam_code: list[dict[str, Bubble]]
    section1: list[dict[str, Bubble]]
    section2: list[dict[str, dict[str, Bubble]]]
    section3: list[list[dict[str, Bubble]]]
    template_gray: np.ndarray


def _bubble(x: float, y: float) -> Bubble:
    return Bubble(center=(float(x), float(y)))


def _build_code_columns(x_values: list[float]) -> list[dict[str, Bubble]]:
    y_values = np.linspace(195.0, 487.0, 10)
    return [
        {str(digit): _bubble(x, y_values[digit]) for digit in range(10)}
        for x in x_values
    ]


def _build_section1() -> list[dict[str, Bubble]]:
    blocks = [
        [176.0, 221.0, 267.0, 312.0],
        [433.0, 478.0, 523.0, 568.0],
        [688.0, 732.0, 777.0, 821.0],
        [942.0, 987.0, 1033.0, 1078.0],
    ]
    y_values = np.linspace(616.0, 868.0, 10)
    questions: list[dict[str, Bubble]] = []
    for x_values in blocks:
        for y in y_values:
            questions.append({label: _bubble(x, y) for label, x in zip("ABCD", x_values)})
    return questions


def _build_section2() -> list[dict[str, dict[str, Bubble]]]:
    pairs = [
        (176.0, 220.0),
        (268.0, 313.0),
        (428.0, 473.0),
        (520.0, 565.0),
        (683.0, 727.0),
        (775.0, 820.0),
        (940.0, 985.0),
        (1032.0, 1076.0),
    ]
    y_values = [1011.0, 1039.0, 1067.0, 1095.0]
    return [
        {
            statement: {"D": _bubble(x_pair[0], y), "S": _bubble(x_pair[1], y)}
            for statement, y in zip("abcd", y_values)
        }
        for x_pair in pairs
    ]


def _build_section3() -> list[list[dict[str, Bubble]]]:
    x_values_by_question = [
        [170.0, 197.0, 225.0, 252.0],
        [333.0, 360.0, 388.0, 415.0],
        [497.0, 524.0, 550.0, 578.0],
        [659.0, 686.0, 713.0, 740.0],
        [822.0, 849.0, 876.0, 903.0],
        [985.0, 1012.0, 1039.0, 1066.0],
    ]
    digit_y = np.linspace(1281.0, 1560.0, 10)
    questions: list[list[dict[str, Bubble]]] = []
    for x_values in x_values_by_question:
        columns: list[dict[str, Bubble]] = []
        for column_index, x in enumerate(x_values):
            options = {str(digit): _bubble(x, digit_y[digit]) for digit in range(10)}
            if column_index == 0:
                options["-"] = _bubble(x, 1219.0)
            elif column_index in (1, 2):
                options[","] = _bubble(x, 1249.0)
            columns.append(options)
        questions.append(columns)
    return questions


def _load_gray_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Khong doc duoc template: {path}")
    if image.shape != (CANONICAL_HEIGHT, CANONICAL_WIDTH):
        image = cv2.resize(image, (CANONICAL_WIDTH, CANONICAL_HEIGHT), interpolation=cv2.INTER_AREA)
    return image


def _square_candidates(gray: np.ndarray) -> list[tuple[float, float]]:
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, global_threshold = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    local_threshold = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        51,
        15,
    )
    candidates: list[tuple[float, float]] = []
    scale = gray.shape[1] / CANONICAL_WIDTH
    min_side = 17.0 * scale
    max_side = 34.0 * scale
    min_area = 250.0 * scale * scale
    max_area = 1100.0 * scale * scale

    for threshold in (global_threshold, local_threshold):
        contours, _ = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            perimeter = cv2.arcLength(contour, True)
            polygon = cv2.approxPolyDP(contour, 0.07 * perimeter, True)
            if not min_area <= area <= max_area:
                continue
            if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                continue
            if not min_side <= min(width, height) <= max(width, height) <= max_side:
                continue
            aspect = width / max(height, 1)
            fill = area / max(width * height, 1)
            if 0.72 <= aspect <= 1.30 and fill >= 0.65:
                center = (x + width / 2.0, y + height / 2.0)
                if not any((center[0] - old[0]) ** 2 + (center[1] - old[1]) ** 2 < 8.0**2 for old in candidates):
                    candidates.append(center)
    return candidates


def _find_corner_markers(gray: np.ndarray) -> dict[str, tuple[float, float]]:
    candidates = _square_candidates(gray)
    height, width = gray.shape
    regions = {
        "top_left": (0.0, width * 0.18, 0.0, height * 0.20, (0.0, 0.0)),
        "top_right": (width * 0.86, width, 0.0, height * 0.20, (float(width), 0.0)),
        "bottom_right": (width * 0.86, width, height * 0.72, height, (float(width), float(height))),
        "bottom_left": (0.0, width * 0.18, height * 0.72, height, (0.0, float(height))),
    }
    selected: dict[str, tuple[float, float]] = {}
    for name, (x1, x2, y1, y2, target) in regions.items():
        matches = [point for point in candidates if x1 <= point[0] <= x2 and y1 <= point[1] <= y2]
        if not matches:
            raise ValueError(f"Thieu moc goc: {name}.")
        selected[name] = min(
            matches,
            key=lambda point: (point[0] - target[0]) ** 2 + (point[1] - target[1]) ** 2,
        )

    polygon = np.float32(
        [selected["top_left"], selected["top_right"], selected["bottom_right"], selected["bottom_left"]]
    )
    coverage = cv2.contourArea(polygon) / float(width * height)
    top_width = np.linalg.norm(polygon[1] - polygon[0])
    bottom_width = np.linalg.norm(polygon[2] - polygon[3])
    left_height = np.linalg.norm(polygon[3] - polygon[0])
    right_height = np.linalg.norm(polygon[2] - polygon[1])
    aspect = ((top_width + bottom_width) / 2.0) / max((left_height + right_height) / 2.0, 1.0)
    target_polygon = np.float32(
        [CORNER_MARKERS["top_left"], CORNER_MARKERS["top_right"], CORNER_MARKERS["bottom_right"], CORNER_MARKERS["bottom_left"]]
    )
    target_width = (np.linalg.norm(target_polygon[1] - target_polygon[0]) + np.linalg.norm(target_polygon[2] - target_polygon[3])) / 2.0
    target_height = (np.linalg.norm(target_polygon[3] - target_polygon[0]) + np.linalg.norm(target_polygon[2] - target_polygon[1])) / 2.0
    target_aspect = target_width / target_height
    if coverage < 0.52 or abs(aspect - target_aspect) > 0.12:
        raise ValueError("Bon moc goc khong tao thanh dung khung phieu.")
    return selected


def detect_square_markers(gray: np.ndarray) -> list[tuple[float, float]]:
    return sorted(_square_candidates(gray), key=lambda point: (point[1], point[0]))


@lru_cache(maxsize=2)
def load_template_layout(template_path: str | Path) -> TemplateLayout:
    gray = _load_gray_image(Path(template_path))
    return TemplateLayout(
        width=CANONICAL_WIDTH,
        height=CANONICAL_HEIGHT,
        marker_centers=dict(CORNER_MARKERS),
        guide_markers=list(GUIDE_MARKERS),
        student_id=_build_code_columns([845.0, 867.0, 889.0, 912.0, 934.0, 956.0, 979.0, 1001.0]),
        exam_code=_build_code_columns([1041.0, 1064.0, 1087.0, 1110.0]),
        section1=_build_section1(),
        section2=_build_section2(),
        section3=_build_section3(),
        template_gray=gray,
    )


def detect_scan_corner_markers(gray: np.ndarray) -> dict[str, tuple[float, float]]:
    return _find_corner_markers(gray)
