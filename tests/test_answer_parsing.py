from __future__ import annotations

import unittest

from werkzeug.datastructures import MultiDict

from app import parse_answer_key, parse_section1, parse_section2, parse_section3


class AnswerParsingTest(unittest.TestCase):
    def test_shorter_exam_answer_key_is_valid(self) -> None:
        key = parse_answer_key(
            MultiDict(
                {
                    "section1": "A B C D " * 5,
                    "section2": "DSDS\nSDDS\nDDSS\nSSDD",
                    "section3": "123\n-12\n305",
                }
            )
        )
        self.assertEqual(len(key["section1"]), 20)
        self.assertEqual(len(key["section2"]), 4)
        self.assertEqual(len(key["section3"]), 3)

    def test_sections_may_be_unused(self) -> None:
        key = parse_answer_key(
            MultiDict({"section1": "A B C D", "section2": "", "section3": ""})
        )
        self.assertEqual(key["section2"], [])
        self.assertEqual(key["section3"], [])

    def test_template_limits_are_enforced(self) -> None:
        with self.assertRaises(ValueError):
            parse_section1("A " * 41)
        with self.assertRaises(ValueError):
            parse_section2("\n".join(["DSDS"] * 9))
        with self.assertRaises(ValueError):
            parse_section3("\n".join(["1"] * 7))

    def test_at_least_one_answer_is_required(self) -> None:
        with self.assertRaises(ValueError):
            parse_answer_key(MultiDict({"section1": "", "section2": "", "section3": ""}))


if __name__ == "__main__":
    unittest.main()
