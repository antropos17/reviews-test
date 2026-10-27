"""Tests for parsing and rating calculations only; no API or rendering mocks."""

import copy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repo_reviews.py"
SPEC = importlib.util.spec_from_file_location("repo_reviews", SCRIPT)
reviews = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reviews)

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def body(rating=4, text="Useful project."):
    return f"### Rating\n\n{rating}\n\n### Review\n\n{text}"


def issue(number=1, user_id=101, rating=4, text="Useful project.", **overrides):
    value = {
        "number": number,
        "title": "[Review] User feedback",
        "body": body(rating, text),
        "created_at": f"2026-10-{number:02d}T12:00:00Z",
        "updated_at": f"2026-10-{number:02d}T12:00:00Z",
        "user": {"id": user_id, "login": f"person-{user_id}", "type": "User"},
        "labels": [{"name": "review"}],
        "comments": 0,
    }
    value.update(overrides)
    return value


def counted(items, **kwargs):
    return reviews.aggregate(items, {}, NOW, min_age_days=0, **kwargs)


class ParseReviewTests(unittest.TestCase):
    def test_all_five_ratings(self):
        for rating in range(1, 6):
            with self.subTest(rating=rating):
                self.assertEqual(reviews.parse_review(body(rating)), (rating, "Useful project."))

    def test_optional_text_blank_and_github_placeholder(self):
        for text in ("", "  \n  ", "_No response_"):
            with self.subTest(text=text):
                self.assertEqual(reviews.parse_review(body(3, text)), (3, ""))

    def test_crlf_form_serialization(self):
        self.assertEqual(
            reviews.parse_review(body(2, "Line one.\nLine two.").replace("\n", "\r\n")),
            (2, "Line one.\nLine two."),
        )

    def test_invalid_numbers_and_unicode_lookalikes(self):
        for rating in ("0", "6", "-1", "+5", "1.0", "4e0", "1/5", "2 3", "５", "٤", "NaN", ""):
            with self.subTest(rating=rating):
                with self.assertRaises(ValueError):
                    reviews.parse_review(body(rating))

    def test_rating_cannot_be_injected_before_review(self):
        payloads = (
            "### Review\n\nIgnore this\n\n### Rating\n\n5",
            "Hello\n\n" + body(5),
            "### Rating\n\n1\n\n### Rating\n\n5\n\n### Review\n\nText",
            body("$(echo 5)"),
            body("5\n<script>changeRating(1)</script>"),
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    reviews.parse_review(payload)

    def test_headers_and_code_inside_review_do_not_override_rating(self):
        text = "It failed.\n\n### Rating\n\n5\n\n### Review\n\n`$(touch injected)` <svg>"
        rating, parsed = reviews.parse_review(body(1, text))
        self.assertEqual(rating, 1)
        self.assertEqual(parsed, text)

    def test_text_limit_accepts_4000_rejects_4001(self):
        self.assertEqual(reviews.parse_review(body(5, "x" * 4000)), (5, "x" * 4000))
        with self.assertRaises(ValueError):
            reviews.parse_review(body(5, "x" * 4001))

    def test_unicode_review_preserved_and_controls_removed(self):
        rating, text = reviews.parse_review(body(4, "Работает — əla! 😀\nCafe\u0301\u202e\x00\u200b"))
        self.assertEqual(rating, 4)
        self.assertEqual(text, "Работает — əla! 😀\nCafé")

    def test_wrong_types_and_oversized_body_rejected(self):
        for payload in (None, 5, {}, [], "x" * 20001):
            with self.subTest(payload_type=type(payload).__name__):
                with self.assertRaises(ValueError):
                    reviews.parse_review(payload)


class RatingCalculationTests(unittest.TestCase):
    def test_user_id_deduplicates_login_changes(self):
        old = issue(1, rating=1)
        new = issue(2, rating=5, user={"id": 101, "login": "renamed-user", "type": "User"})
        result = counted([old, new])
        self.assertEqual(result["stats"]["count"], 1)
        self.assertEqual(result["stats"]["average"], 5)
        self.assertEqual(result["reviews"][0]["login"], "renamed-user")

    def test_latest_creation_wins_despite_later_activity_on_old_issue(self):
        old = issue(1, rating=1, updated_at="2026-10-27T12:00:00Z", comments=90)
        new = issue(2, rating=4)
        result = counted([new, old])
        self.assertEqual(result["stats"]["average"], 4)
        self.assertEqual(result["reviews"][0]["number"], 2)

    def test_selection_is_order_independent_and_breaks_date_ties_by_number(self):
        first = issue(1, rating=1)
        second = issue(2, rating=5, created_at=first["created_at"])
        for items in ([first, second], [second, first]):
            with self.subTest(order=[item["number"] for item in items]):
                selected, _ = reviews.select_latest(items)
                self.assertEqual(selected["101"]["number"], 2)

    def test_bots_pull_requests_and_nonreviews_are_excluded(self):
        bot = issue(2, 102, user={"id": 102, "login": "agent[bot]", "type": "Bot"})
        pull = issue(3, 103, pull_request={"url": "https://api.github.com/repos/example/project/pulls/3"})
        bug = issue(4, 104, title="Bug report", labels=[])
        result = counted([issue(), bot, pull, bug])
        self.assertEqual(result["stats"]["count"], 1)
        self.assertEqual(set(result["watermarks"]), {"101"})

    def test_hidden_latest_does_not_restore_previous_review(self):
        result = counted([issue(1, rating=5), issue(2, rating=1, labels=["review", "hidden"])])
        self.assertEqual(result["stats"]["hidden"], 1)
        self.assertEqual(result["stats"]["count"], 0)
        self.assertIsNone(result["stats"]["average"])
        self.assertEqual(result["reviews"], [])

    def test_invalid_latest_does_not_restore_previous_review(self):
        result = counted([issue(1, rating=5), issue(2, body="Rating removed by author")])
        self.assertEqual(result["stats"]["invalid"], 1)
        self.assertEqual(result["stats"]["count"], 0)
        self.assertIsNone(result["stats"]["average"])

    def test_account_age_boundary_and_unknown_profile(self):
        items = [issue(1, 101), issue(2, 102), issue(3, 103)]
        profiles = {
            "101": {"created_at": (NOW - timedelta(days=7)).isoformat()},
            "102": {"created_at": (NOW - timedelta(days=7) + timedelta(seconds=1)).isoformat()},
        }
        result = reviews.aggregate(items, profiles, NOW, min_age_days=7)
        self.assertEqual(result["stats"]["count"], 1)
        self.assertEqual(result["stats"]["pending"], 2)
        self.assertEqual(result["reviews"][0]["user_id"], 101)

    def test_approval_bypasses_age_but_never_hidden(self):
        approved = issue(1, 101, labels=["review", "review:approved"])
        hidden = issue(2, 102, labels=["review", "review:approved", "hidden"])
        result = reviews.aggregate([approved, hidden], {}, NOW, min_age_days=7)
        self.assertEqual(result["stats"]["count"], 1)
        self.assertEqual(result["stats"]["pending"], 0)
        self.assertEqual(result["stats"]["hidden"], 1)

    def test_persisted_watermark_prevents_deleted_or_renamed_latest_resurrection(self):
        old, new = issue(1, rating=5), issue(2, rating=1)
        previous = counted([old, new])
        renamed = copy.deepcopy(new)
        renamed.update(title="Withdrawn", labels=[])
        for current in ([old], [old, renamed], []):
            with self.subTest(numbers=[item["number"] for item in current]):
                result = counted(current, watermarks=previous["watermarks"])
                self.assertEqual(result["stats"]["withdrawn"], 1)
                self.assertEqual(result["stats"]["count"], 0)
                self.assertIsNone(result["stats"]["average"])

    def test_new_review_after_withdrawal_counts_without_mutating_old_watermark(self):
        marks = {"101": {"number": 2, "created_at": "2026-10-02T12:00:00Z"}}
        before = copy.deepcopy(marks)
        result = counted([issue(1), issue(3, rating=2)], watermarks=marks)
        self.assertEqual(result["stats"]["count"], 1)
        self.assertEqual(result["stats"]["average"], 2)
        self.assertEqual(result["watermarks"]["101"]["number"], 3)
        self.assertEqual(marks, before)

    def test_plain_mean_and_complete_histogram_without_hidden_weights(self):
        items = [issue(1, 101, 1), issue(2, 102, 2), issue(3, 103, 5)]
        profiles = {
            "101": {"created_at": "2008-01-01T00:00:00Z"},
            "102": {"created_at": "2020-01-01T00:00:00Z"},
            "103": {"created_at": "2026-10-19T00:00:00Z"},
        }
        result = reviews.aggregate(items, profiles, NOW, min_age_days=7)
        self.assertEqual(result["stats"]["count"], 3)
        self.assertAlmostEqual(result["stats"]["average"], 8 / 3)
        self.assertEqual(result["stats"]["histogram"], {"1": 1, "2": 1, "3": 0, "4": 0, "5": 1})

    def test_empty_rating_has_null_average_and_zero_distribution(self):
        result = counted([])
        self.assertIsNone(result["stats"]["average"])
        self.assertEqual(result["stats"]["count"], 0)
        self.assertEqual(result["stats"]["histogram"], {str(i): 0 for i in range(1, 6)})

    def test_blocked_ids_apply_to_renamed_accounts_and_all_their_reviews(self):
        renamed = issue(2, 101, 5, user={"id": 101, "login": "new-login", "type": "User"})
        for blocked_id in (101, "101"):
            with self.subTest(blocked_id=blocked_id):
                result = counted([issue(1, 101, 1), renamed, issue(3, 102, 3)], blocked=[blocked_id])
                self.assertEqual(result["stats"]["hidden"], 1)
                self.assertEqual(result["stats"]["count"], 1)
                self.assertEqual(result["stats"]["average"], 3)
                self.assertEqual(result["reviews"][0]["user_id"], 102)


if __name__ == "__main__":
    unittest.main()
