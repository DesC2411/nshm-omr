from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .template import Bubble, detect_scan_corner_markers, detect_square_markers, load_template_layout


@dataclass(frozen=True)
class Calibration:
    threshold: float
    margin: float
    baseline: float
    peak: float


@dataclass(frozen=True)
class ScoreMaps:
    gray: np.ndarray
    normalized: np.ndarray
    binary: np.ndarray


class OMRProcessor:
    def __init__(self, template_path: str | Path):
        self.template = load_template_layout(template_path)

    def preview(self, image_bytes: bytes) -> dict[str, Any]:
        image = self._decode_upload(image_bytes)
        return self._preview_frame(image)

    def grade(self, image_bytes: bytes, answer_key: dict[str, Any]) -> dict[str, Any]:
        source = self._decode_upload(image_bytes)
        warped = self._align_to_template(source)
        warped = self._refine_with_markers(warped)
        quality = self._measure_quality(source, warped)
        score_maps = self._prepare_score_maps(warped)

        calibration = self._calibrate(score_maps)
        student_id, student_id_items = self._decode_code_details(self.template.student_id, score_maps, calibration)
        exam_code, exam_code_items = self._decode_code_details(self.template.exam_code, score_maps, calibration)
        result = {
            "student_id": student_id,
            "exam_code": exam_code,
            "student_id_status": "ok" if all(item["status"] == "ok" for item in student_id_items) else "review",
            "exam_code_status": "ok" if all(item["status"] == "ok" for item in exam_code_items) else "review",
            "quality": quality,
        }

        section1_items, section1_correct = self._grade_section1(score_maps, answer_key["section1"], calibration)
        section2_items, section2_correct = self._grade_section2(score_maps, answer_key["section2"], calibration)
        section3_items, section3_correct = self._grade_section3(score_maps, answer_key["section3"], calibration)

        total_units = len(section1_items) + len(section2_items) + len(section3_items)
        total_correct = section1_correct + section2_correct + section3_correct

        overlay = self._draw_overlay(
            warped.copy(),
            student_id_items=student_id_items,
            exam_code_items=exam_code_items,
            section1_items=section1_items,
            section2_items=section2_items,
            section3_items=section3_items,
        )
        overlay_b64 = base64.b64encode(cv2.imencode(".png", overlay)[1].tobytes()).decode("ascii")
        review_reasons: list[str] = []
        if result["student_id_status"] != "ok":
            review_reasons.append("Mã học sinh chưa chắc chắn")
        if result["exam_code_status"] != "ok":
            review_reasons.append("Mã đề chưa chắc chắn")
        if quality["status"] != "accepted":
            review_reasons.append("Căn chỉnh trang cần kiểm tra")
        multiple_count = sum(
            "multiple" in str(item.get("status", ""))
            for section in (section1_items, section2_items, section3_items)
            for item in section
        )
        if multiple_count:
            review_reasons.append(f"{multiple_count} vùng có nhiều lựa chọn")

        result.update(
            {
                "section1": section1_items,
                "section2": section2_items,
                "section3": section3_items,
                "totals": {
                    "section1": {"correct": section1_correct, "total": len(section1_items)},
                    "section2": {"correct": section2_correct, "total": len(section2_items)},
                    "section3": {"correct": section3_correct, "total": len(section3_items)},
                    "overall": {"correct": total_correct, "total": total_units},
                    "score_10": round((total_correct / total_units) * 10.0, 2) if total_units else 0.0,
                },
                "calibration": {
                    "threshold": round(calibration.threshold, 3),
                    "margin": round(calibration.margin, 3),
                },
                "review_reasons": review_reasons,
                "needs_review": bool(review_reasons),
                "overlay_base64": overlay_b64,
            }
        )
        return result

    def _measure_quality(self, source: np.ndarray, aligned: np.ndarray) -> dict[str, Any]:
        source_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        aligned_gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
        markers = detect_square_markers(aligned_gray)
        matches = self._match_guide_markers(markers)
        errors = [
            float(np.hypot(scan[0] - template[0], scan[1] - template[1]))
            for scan, template in matches
        ]
        marker_error = float(np.mean(errors)) if errors else 999.0
        sharpness = float(cv2.Laplacian(source_gray, cv2.CV_32F).var())
        low, high = np.quantile(source_gray, [0.05, 0.95])
        dynamic_range = float(high - low)
        marker_ratio = min(len(matches) / max(len(self.template.guide_markers), 1), 1.0)
        alignment_score = max(0.0, 1.0 - marker_error / 12.0)
        quality_score = (marker_ratio * 0.62) + (alignment_score * 0.38)

        if len(matches) < 6 or marker_error > 14.0:
            status = "rejected"
        elif len(matches) < 8 or marker_error > 7.0 or dynamic_range < 70.0:
            status = "review"
        else:
            status = "accepted"
        return {
            "status": status,
            "score": round(quality_score, 3),
            "guide_markers": len(matches),
            "marker_error": round(marker_error, 2),
            "brightness": round(float(source_gray.mean()), 1),
            "dynamic_range": round(dynamic_range, 1),
            "sharpness": round(sharpness, 1),
        }

    def _decode_upload(self, image_bytes: bytes) -> np.ndarray:
        buffer = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Chi ho tro anh JPG/PNG. Hay doi file scan sang anh truoc khi upload.")
        return image

    def _preview_frame(self, image: np.ndarray) -> dict[str, Any]:
        height, width = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        brightness = float(gray.mean())
        corners, candidate_score = self._detect_sheet_candidate(image, preview=True)
        target_aspect = self.template.width / float(self.template.height)

        result = {
            "detected": False,
            "ready": False,
            "size": {"width": width, "height": height},
            "metrics": {
                "sharpness": round(sharpness, 1),
                "brightness": round(brightness, 1),
                "coverage": 0.0,
                "aspect_error": None,
                "confidence": 0.0,
            },
            "corners": [],
        }

        if corners is None:
            return result

        ordered = self._order_corners(corners.astype(np.float32))
        quad_width, quad_height = self._quad_size(ordered)
        aspect = quad_width / max(quad_height, 1.0)
        aspect_error = min(abs(aspect - target_aspect), abs((1.0 / aspect) - target_aspect))
        coverage = float(cv2.contourArea(ordered) / max(width * height, 1))

        ready = (
            coverage >= 0.42
            and sharpness >= 18.0
            and 70.0 <= brightness <= 245.0
            and aspect_error <= 0.16
        )
        result["detected"] = True
        result["ready"] = ready
        result["metrics"] = {
            "sharpness": round(sharpness, 1),
            "brightness": round(brightness, 1),
            "coverage": round(coverage, 3),
            "aspect_error": round(aspect_error, 3),
            "confidence": round(min(max(candidate_score / 5.5, 0.0), 1.0), 3),
        }
        result["corners"] = [
            {"x": round(float(point[0] / width), 5), "y": round(float(point[1] / height), 5)}
            for point in ordered
        ]
        return result

    def _align_to_template(self, image: np.ndarray) -> np.ndarray:
        # CamScanner pages expose the four printed corner markers reliably. Using
        # those markers directly avoids accepting a large internal rectangle as
        # the page contour when the background has shadows or gradients.
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        markers = detect_scan_corner_markers(gray)
        source = np.float32(
            [
                markers["top_left"],
                markers["top_right"],
                markers["bottom_right"],
                markers["bottom_left"],
            ]
        )
        target = np.float32(
            [
                self.template.marker_centers["top_left"],
                self.template.marker_centers["top_right"],
                self.template.marker_centers["bottom_right"],
                self.template.marker_centers["bottom_left"],
            ]
        )
        matrix = cv2.getPerspectiveTransform(source, target)
        warped = cv2.warpPerspective(
            image,
            matrix,
            (self.template.width, self.template.height),
            borderValue=(255, 255, 255),
        )
        return self._match_orientation(warped)

    def _flatten_sheet(self, image: np.ndarray) -> np.ndarray:
        corners = self._detect_sheet_corners(image)
        if corners is None:
            return image

        destination = np.float32(
            [
                [0, 0],
                [self.template.width - 1, 0],
                [self.template.width - 1, self.template.height - 1],
                [0, self.template.height - 1],
            ]
        )
        matrix = cv2.getPerspectiveTransform(corners, destination)
        flattened = cv2.warpPerspective(
            image,
            matrix,
            (self.template.width, self.template.height),
            borderValue=(255, 255, 255),
        )
        source_aspect = image.shape[1] / float(image.shape[0])
        template_aspect = self.template.width / float(self.template.height)
        if abs(source_aspect - template_aspect) < 0.03:
            return flattened
        return self._tighten_flattened_page(flattened)

    def _tighten_flattened_page(self, image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, page_mask = cv2.threshold(gray, 250, 255, cv2.THRESH_BINARY_INV)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31))
        page_mask = cv2.morphologyEx(page_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        page_mask = cv2.morphologyEx(page_mask, cv2.MORPH_OPEN, kernel, iterations=1)

        candidate = self._best_sheet_candidate(page_mask)
        if candidate is None:
            return image

        corners, score = candidate
        image_area = float(image.shape[0] * image.shape[1])
        contour_area = cv2.contourArea(corners.astype(np.float32))
        if contour_area < image_area * 0.72 or score < 4.0:
            return image

        destination = np.float32(
            [
                [0, 0],
                [self.template.width - 1, 0],
                [self.template.width - 1, self.template.height - 1],
                [0, self.template.height - 1],
            ]
        )
        matrix = cv2.getPerspectiveTransform(corners.astype(np.float32), destination)
        return cv2.warpPerspective(
            image,
            matrix,
            (self.template.width, self.template.height),
            borderValue=(255, 255, 255),
        )

    def _detect_sheet_corners(self, image: np.ndarray) -> np.ndarray | None:
        corners, _ = self._detect_sheet_candidate(image, preview=False)
        return corners

    def _detect_sheet_candidate(self, image: np.ndarray, *, preview: bool) -> tuple[np.ndarray | None, float]:
        max_side = 1800
        height, width = image.shape[:2]
        scale = 1.0
        working = image
        if max(height, width) > max_side:
            scale = max_side / float(max(height, width))
            working = cv2.resize(
                image,
                (int(round(width * scale)), int(round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )

        gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
        candidates = self._detect_sheet_candidates_from_masks(gray, preview=preview)
        scored_candidates = [candidate for candidate in candidates if candidate is not None]
        if not scored_candidates:
            return None, 0.0

        best_corners, best_score = max(scored_candidates, key=lambda item: item[1])
        if scale != 1.0:
            best_corners = best_corners / scale
        return best_corners.astype(np.float32), float(best_score)

    def _detect_sheet_candidates_from_masks(
        self,
        gray: np.ndarray,
        *,
        preview: bool,
    ) -> list[tuple[np.ndarray, float] | None]:
        blur_kernel = (5, 5) if preview else (7, 7)
        blurred = cv2.GaussianBlur(gray, blur_kernel, 0)
        norm = cv2.normalize(blurred, None, 0, 255, cv2.NORM_MINMAX)
        kernel_size = 7 if preview else 9
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))

        _, bright_mask = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_OPEN, kernel, iterations=1)

        edges = cv2.Canny(norm, 50 if preview else 60, 160 if preview else 180)
        edges = cv2.dilate(edges, kernel, iterations=1)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

        masks = [bright_mask, edges]
        if preview:
            adaptive = cv2.adaptiveThreshold(
                norm,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                9,
            )
            adaptive = cv2.morphologyEx(adaptive, cv2.MORPH_CLOSE, kernel, iterations=1)
            adaptive = cv2.morphologyEx(adaptive, cv2.MORPH_OPEN, kernel, iterations=1)
            masks.extend(
                [
                    adaptive,
                    cv2.bitwise_or(adaptive, edges),
                    cv2.bitwise_or(bright_mask, edges),
                ]
            )

        min_area_ratio = 0.08 if preview else 0.18
        min_width_ratio = 0.26 if preview else 0.45
        min_height_ratio = 0.26 if preview else 0.45
        center_weight = 0.8 if preview else 0.15
        return [
            self._best_sheet_candidate(
                mask,
                min_area_ratio=min_area_ratio,
                min_width_ratio=min_width_ratio,
                min_height_ratio=min_height_ratio,
                center_weight=center_weight,
            )
            for mask in masks
        ]

    def _best_sheet_candidate(
        self,
        mask: np.ndarray,
        *,
        min_area_ratio: float = 0.18,
        min_width_ratio: float = 0.45,
        min_height_ratio: float = 0.45,
        center_weight: float = 0.0,
    ) -> tuple[np.ndarray, float] | None:
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        image_area = float(mask.shape[0] * mask.shape[1])
        target_aspect = self.template.width / float(self.template.height)

        best: tuple[np.ndarray, float] | None = None
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < image_area * min_area_ratio:
                continue

            perimeter = cv2.arcLength(contour, True)
            approximated = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
            shapes: list[np.ndarray] = []
            if len(approximated) == 4 and cv2.isContourConvex(approximated):
                shapes.append(approximated.reshape(4, 2).astype(np.float32))
            shapes.append(cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float32))

            for shape in shapes:
                ordered = self._order_corners(shape)
                quad_width, quad_height = self._quad_size(ordered)
                if quad_width < mask.shape[1] * min_width_ratio or quad_height < mask.shape[0] * min_height_ratio:
                    continue

                aspect = quad_width / max(quad_height, 1.0)
                aspect_error = min(abs(aspect - target_aspect), abs((1.0 / aspect) - target_aspect))
                rectangularity = area / max(quad_width * quad_height, 1.0)
                center = ordered.mean(axis=0)
                center_dx = abs(float(center[0]) - (mask.shape[1] / 2.0)) / max(mask.shape[1], 1)
                center_dy = abs(float(center[1]) - (mask.shape[0] / 2.0)) / max(mask.shape[0], 1)
                center_bonus = max(0.0, 1.0 - ((center_dx + center_dy) * 1.35))
                score = (area / image_area) * 5.0 + rectangularity - (aspect_error * 2.2) + (center_bonus * center_weight)

                if best is None or score > best[1]:
                    best = (ordered, score)
        return best

    def _order_corners(self, points: np.ndarray) -> np.ndarray:
        sums = points.sum(axis=1)
        diffs = np.diff(points, axis=1).reshape(-1)
        ordered = np.zeros((4, 2), dtype=np.float32)
        ordered[0] = points[np.argmin(sums)]
        ordered[1] = points[np.argmin(diffs)]
        ordered[2] = points[np.argmax(sums)]
        ordered[3] = points[np.argmax(diffs)]
        return ordered

    def _quad_size(self, points: np.ndarray) -> tuple[float, float]:
        top = float(np.linalg.norm(points[1] - points[0]))
        bottom = float(np.linalg.norm(points[2] - points[3]))
        left = float(np.linalg.norm(points[3] - points[0]))
        right = float(np.linalg.norm(points[2] - points[1]))
        return (top + bottom) / 2.0, (left + right) / 2.0

    def _refine_with_markers(self, warped: np.ndarray) -> np.ndarray:
        candidate = warped
        for _ in range(2):
            gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
            detected_markers = detect_square_markers(gray)
            matches = self._match_guide_markers(detected_markers)
            if len(matches) < 8:
                return candidate

            source = np.float32([scan for scan, _ in matches])
            target = np.float32([template for _, template in matches])
            matrix, mask = cv2.findHomography(source, target, cv2.RANSAC, 8.0)
            if matrix is None or mask is None or int(mask.sum()) < 8:
                return candidate

            candidate = cv2.warpPerspective(
                candidate,
                matrix,
                (self.template.width, self.template.height),
                borderValue=(255, 255, 255),
            )
        return candidate

    def _match_guide_markers(
        self,
        detected_markers: list[tuple[float, float]],
    ) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        remaining = list(detected_markers)
        matches: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for template_point in self.template.guide_markers:
            if not remaining:
                break
            distances = [
                ((point[0] - template_point[0]) ** 2 + (point[1] - template_point[1]) ** 2, index)
                for index, point in enumerate(remaining)
            ]
            distance, index = min(distances, key=lambda item: item[0])
            if distance > 52 ** 2:
                continue
            matches.append((remaining.pop(index), template_point))
        return matches

    def _match_orientation(self, warped: np.ndarray) -> np.ndarray:
        candidates = [warped, cv2.rotate(warped, cv2.ROTATE_180)]
        scores: list[float] = []
        for candidate in candidates:
            gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
            height, width = gray.shape
            # The template has a distinctive vertical stack of black bars on
            # the upper-right edge. This signal survives shadows better than a
            # full-page pixel difference and disambiguates a 180-degree scan.
            barcode = gray[int(height * 0.05) : int(height * 0.32), int(width * 0.91) : int(width * 0.97)]
            scores.append(float(np.mean(barcode < 105)))
        return candidates[int(np.argmax(scores))]

    def _prepare_score_maps(self, image: np.ndarray) -> ScoreMaps:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        background = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=21, sigmaY=21)
        normalized = cv2.divide(enhanced, background, scale=255)
        binary = cv2.adaptiveThreshold(
            normalized,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            7,
        )
        binary = cv2.medianBlur(binary, 3)
        return ScoreMaps(gray=enhanced, normalized=normalized, binary=binary)

    def _bubble_score(self, score_maps: ScoreMaps, bubble: Bubble) -> float:
        height, width = score_maps.gray.shape
        cx = int(round(bubble.center[0]))
        cy = int(round(bubble.center[1]))
        radius = float(bubble.radius)
        outer_radius = max(6, int(round(radius * 1.4)))

        x1 = max(cx - outer_radius, 0)
        y1 = max(cy - outer_radius, 0)
        x2 = min(cx + outer_radius + 1, width)
        y2 = min(cy + outer_radius + 1, height)

        yy, xx = np.ogrid[y1:y2, x1:x2]
        distances = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        core_mask = distances <= max(radius * 0.36, 4.5)
        ring_mask = (distances >= radius * 0.62) & (distances <= radius * 1.15)
        surround_mask = (distances >= radius * 0.45) & (distances <= radius * 1.4)

        local_binary = score_maps.binary[y1:y2, x1:x2]
        local_normalized = score_maps.normalized[y1:y2, x1:x2]

        core_ink = float(local_binary[core_mask].mean() / 255.0) if np.any(core_mask) else 0.0
        ring_ink = float(local_binary[ring_mask].mean() / 255.0) if np.any(ring_mask) else 0.0
        core_darkness = float(1.0 - local_normalized[core_mask].mean() / 255.0) if np.any(core_mask) else 0.0
        surround_darkness = (
            float(1.0 - local_normalized[surround_mask].mean() / 255.0) if np.any(surround_mask) else 0.0
        )
        contrast = max(core_darkness - surround_darkness, 0.0)

        return (core_ink * 0.72) + (contrast * 0.28) - (ring_ink * 0.08)

    def _all_scores(self, score_maps: ScoreMaps) -> list[float]:
        scores: list[float] = []

        for column in self.template.student_id:
            for bubble in column.values():
                scores.append(self._bubble_score(score_maps, bubble))
        for column in self.template.exam_code:
            for bubble in column.values():
                scores.append(self._bubble_score(score_maps, bubble))
        for question in self.template.section1:
            for bubble in question.values():
                scores.append(self._bubble_score(score_maps, bubble))
        for question in self.template.section2:
            for statement in question.values():
                for bubble in statement.values():
                    scores.append(self._bubble_score(score_maps, bubble))
        for question in self.template.section3:
            for column in question:
                for bubble in column.values():
                    scores.append(self._bubble_score(score_maps, bubble))
        return scores

    def _calibrate(self, score_maps: ScoreMaps) -> Calibration:
        scores = np.array(self._all_scores(score_maps), dtype=np.float32)
        baseline = float(np.quantile(scores, 0.55))
        peak = float(np.quantile(scores, 0.992))
        spread = max(peak - baseline, 0.14)
        threshold = 0.15
        margin = max(spread * 0.17, 0.045)
        return Calibration(threshold=threshold, margin=margin, baseline=baseline, peak=peak)

    def _pick_single(
        self,
        scores: dict[str, float],
        calibration: Calibration,
        *,
        minimum_score: float | None = None,
        use_median_blank: bool = True,
    ) -> tuple[str, str]:
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        label, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        median = float(np.median(list(scores.values())))
        threshold = max(calibration.threshold, minimum_score or calibration.threshold)
        if best < threshold:
            return "", "blank"
        if use_median_blank and best - median < calibration.margin:
            return "", "blank"
        if second >= best - (calibration.margin * 0.75) and second >= calibration.threshold:
            return "", "multiple"
        return label, "ok"

    def _decode_code(
        self,
        columns: list[dict[str, Bubble]],
        score_maps: ScoreMaps,
        calibration: Calibration,
    ) -> str:
        code, _ = self._decode_code_details(columns, score_maps, calibration)
        return code

    def _decode_code_details(
        self,
        columns: list[dict[str, Bubble]],
        score_maps: ScoreMaps,
        calibration: Calibration,
    ) -> tuple[str, list[dict[str, Any]]]:
        digits: list[str] = []
        items: list[dict[str, Any]] = []
        for index, column in enumerate(columns, start=1):
            scores = {label: self._bubble_score(score_maps, bubble) for label, bubble in column.items()}
            selected, status = self._pick_code_digit(scores, calibration)
            digits.append(selected or "?")
            items.append(
                {
                    "column": index,
                    "selected": selected or "",
                    "status": status,
                    "bubbles": column,
                }
            )
        return "".join(digits), items

    def _pick_code_digit(
        self,
        scores: dict[str, float],
        calibration: Calibration,
    ) -> tuple[str, str]:
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        label, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0

        # Bubble ma hoc sinh/ma de nho hon, de bi roi vao blank neu dung chung nguong chat.
        threshold = max(calibration.threshold - 0.03, 0.12)
        if best < threshold:
            return "", "blank"
        if second >= best - (calibration.margin * 0.65) and second >= threshold:
            return "", "multiple"
        return label, "ok"

    def _grade_section1(
        self,
        score_maps: ScoreMaps,
        answer_key: list[str],
        calibration: Calibration,
    ) -> tuple[list[dict[str, Any]], int]:
        items: list[dict[str, Any]] = []
        correct = 0
        for index, question in enumerate(self.template.section1, start=1):
            scores = {label: self._bubble_score(score_maps, bubble) for label, bubble in question.items()}
            selected, status = self._pick_single(scores, calibration)
            expected = answer_key[index - 1]
            is_correct = selected == expected
            correct += int(is_correct)
            items.append(
                {
                    "question": index,
                    "expected": expected,
                    "selected": selected or "-",
                    "status": status,
                    "correct": is_correct,
                    "bubbles": question,
                }
            )
        return items, correct

    def _grade_section2(
        self,
        score_maps: ScoreMaps,
        answer_key: list[list[str]],
        calibration: Calibration,
    ) -> tuple[list[dict[str, Any]], int]:
        items: list[dict[str, Any]] = []
        correct = 0
        for question_index, question in enumerate(self.template.section2, start=1):
            for statement_index, statement in enumerate("abcd"):
                options = question[statement]
                scores = {label: self._bubble_score(score_maps, bubble) for label, bubble in options.items()}
                selected, status = self._pick_single(scores, calibration, use_median_blank=False)
                expected = answer_key[question_index - 1][statement_index]
                is_correct = selected == expected
                correct += int(is_correct)
                items.append(
                    {
                        "question": question_index,
                        "statement": statement,
                        "expected": expected,
                        "selected": selected or "-",
                        "status": status,
                        "correct": is_correct,
                        "bubbles": options,
                    }
                )
        return items, correct

    def _grade_section3(
        self,
        score_maps: ScoreMaps,
        answer_key: list[str],
        calibration: Calibration,
    ) -> tuple[list[dict[str, Any]], int]:
        items: list[dict[str, Any]] = []
        correct = 0
        for question_index, question in enumerate(self.template.section3, start=1):
            positions: list[str] = []
            statuses: list[str] = []
            for column in question:
                scores = {label: self._bubble_score(score_maps, bubble) for label, bubble in column.items()}
                selected, status = self._pick_single(
                    scores,
                    calibration,
                    minimum_score=max(calibration.threshold + (calibration.margin * 0.6), 0.42),
                )
                positions.append(selected)
                statuses.append(status)
            normalized = "".join(value for value in positions if value)
            expected = answer_key[question_index - 1]
            expected_positions = list(expected) + [""] * max(0, 4 - len(expected))
            expected_positions = expected_positions[:4]
            status = "ok" if all(item == "ok" for item in statuses) else ",".join(statuses)
            is_correct = normalized == expected
            correct += int(is_correct)
            items.append(
                {
                    "question": question_index,
                    "expected": expected,
                    "selected": normalized or "-",
                    "selected_positions": positions,
                    "expected_positions": expected_positions,
                    "status": status,
                    "correct": is_correct,
                    "columns": question,
                }
            )
        return items, correct

    def _draw_overlay(
        self,
        image: np.ndarray,
        *,
        student_id_items: list[dict[str, Any]],
        exam_code_items: list[dict[str, Any]],
        section1_items: list[dict[str, Any]],
        section2_items: list[dict[str, Any]],
        section3_items: list[dict[str, Any]],
    ) -> np.ndarray:
        blue = (207, 159, 43)
        green = (46, 204, 113)
        red = (60, 76, 231)

        def draw_selected_only(bubbles: dict[str, Bubble], selected: str) -> None:
            if not selected or selected not in bubbles:
                return
            center = tuple(int(round(value)) for value in bubbles[selected].center)
            radius = int(round(bubbles[selected].radius))
            cv2.circle(image, center, radius + 4, red, 3)
            cv2.circle(image, center, max(3, radius // 3), red, -1)

        def draw_group(bubbles: dict[str, Bubble], selected: str, expected: str) -> None:
            for label, bubble in bubbles.items():
                center = tuple(int(round(value)) for value in bubble.center)
                radius = int(round(bubble.radius))
                cv2.circle(image, center, radius, blue, 1)
            if expected and expected in bubbles:
                center = tuple(int(round(value)) for value in bubbles[expected].center)
                radius = int(round(bubbles[expected].radius))
                cv2.circle(image, center, radius + 4, green, 2)
            if selected and selected in bubbles:
                center = tuple(int(round(value)) for value in bubbles[selected].center)
                radius = int(round(bubbles[selected].radius))
                cv2.circle(image, center, radius + 1, red, 2)

        for item in student_id_items:
            draw_selected_only(item["bubbles"], item["selected"])

        for item in exam_code_items:
            draw_selected_only(item["bubbles"], item["selected"])

        for item in section1_items:
            draw_group(
                item["bubbles"],
                item["selected"] if item["selected"] != "-" else "",
                item["expected"],
            )

        for item in section2_items:
            draw_group(
                item["bubbles"],
                item["selected"] if item["selected"] != "-" else "",
                item["expected"],
            )

        for item in section3_items:
            for index, column in enumerate(item["columns"]):
                draw_group(
                    column,
                    item["selected_positions"][index] if index < len(item["selected_positions"]) else "",
                    item["expected_positions"][index] if index < len(item["expected_positions"]) else "",
                )

        return image
