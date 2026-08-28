"""Tests for testimonial spam filtering."""

import pytest

from app.testimonial_spam import (
    SpamAction,
    evaluate_testimonial_spam,
    reset_spam_state_for_tests,
    score_testimonial_submission,
)


@pytest.fixture(autouse=True)
def _clear_spam_state():
    reset_spam_state_for_tests()
    yield
    reset_spam_state_for_tests()


def test_legitimate_homepage_scores_low(app):
    with app.app_context():
        score, _ = score_testimonial_submission(
            quote="Thank you so much, I really enjoyed this trip in Shanghai.",
            author_name="Liv B",
            organization="Ransom Everglades School",
            source="homepage",
        )
        assert score < 3


def test_prod_spam_url_and_name_eq_org_drops(app):
    with app.app_context():
        action, score, _ = evaluate_testimonial_spam(
            {
                "quote": "<a href=https://bayra.market/x>jewelry</a>",
                "author_name": "GeorgeSar",
                "organization": "GeorgeSar",
            },
            source="homepage",
            ip="1.2.3.4",
        )
        assert score >= 5
        assert action == SpamAction.DROP_SILENT


def test_suspicious_rejected_not_dropped(app):
    with app.app_context():
        action, score, _ = evaluate_testimonial_spam(
            {
                "quote": "Looking for effective strategies to increase my website traffic.",
                "author_name": "Alex",
                "organization": "",
            },
            source="homepage",
            ip="5.6.7.8",
        )
        assert score < 5
        assert action in (SpamAction.ALLOW, SpamAction.REJECT_SILENT)


def test_honeypot_drops_without_score(app):
    with app.app_context():
        action, score, reasons = evaluate_testimonial_spam(
            {
                "website": "http://spam.example",
                "quote": "Thank you for the wonderful trip experience!",
                "author_name": "Alex",
            },
            source="homepage",
            ip="9.9.9.9",
        )
        assert action == SpamAction.DROP_SILENT
        assert score == 99
        assert "honeypot" in reasons


def test_rate_limit_blocks_burst(app):
    with app.app_context():
        ip = "10.0.0.1"
        for i in range(3):
            data = {
                "quote": f"This trip was memorable and well organized for group {i}.",
                "author_name": "Jamie",
                "organization": "Test School",
            }
            action, _, _ = evaluate_testimonial_spam(data, source="homepage", ip=ip)
            assert action == SpamAction.ALLOW
        data = {
            "quote": "This trip was memorable and well organized for group fourth.",
            "author_name": "Jamie",
            "organization": "Test School",
        }
        action, _, reasons = evaluate_testimonial_spam(data, source="homepage", ip=ip)
        assert action == SpamAction.DROP_SILENT
        assert "rate_limit" in reasons


def test_feedback_threshold_more_lenient(app):
    with app.app_context():
        action, score, _ = evaluate_testimonial_spam(
            {
                "quote": "Great trip overall, would recommend to other schools.",
                "author_name": "Jamie Lee",
                "organization": "",
                "firstName": "Jamie",
                "lastName": "Lee",
            },
            source="feedback",
            ip="10.0.0.2",
        )
        assert score == 0
        assert action == SpamAction.ALLOW


def test_cleanup_old_rejected_testimonials(app):
    from datetime import datetime, timedelta

    from app import db
    from app.models import Testimonial
    from app.tasks import cleanup_old_rejected_testimonials

    with app.app_context():
        old = Testimonial(
            quote="Old rejected spam entry for cleanup test.",
            author_name="Spambot",
            status="rejected",
            source="homepage",
            created_at=datetime.utcnow() - timedelta(days=100),
        )
        recent = Testimonial(
            quote="Recent rejected entry should stay for now.",
            author_name="Spambot2",
            status="rejected",
            source="homepage",
            created_at=datetime.utcnow() - timedelta(days=10),
        )
        pending = Testimonial(
            quote="Pending should never be deleted by cleanup.",
            author_name="Real User",
            status="pending",
            source="homepage",
            created_at=datetime.utcnow() - timedelta(days=100),
        )
        db.session.add_all([old, recent, pending])
        db.session.commit()
        old_id, recent_id, pending_id = old.id, recent.id, pending.id

        deleted = cleanup_old_rejected_testimonials(retention_days=90)
        assert deleted >= 1
        assert Testimonial.query.get(old_id) is None
        assert Testimonial.query.get(recent_id) is not None
        assert Testimonial.query.get(pending_id) is not None

        db.session.delete(Testimonial.query.get(recent_id))
        db.session.delete(Testimonial.query.get(pending_id))
        db.session.commit()
