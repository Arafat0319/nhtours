"""Manage Payment History hides voided/failed attempts."""
from types import SimpleNamespace

from app.payments import payment_hidden_from_admin_history


def test_hides_failed_and_canceled():
    assert payment_hidden_from_admin_history(SimpleNamespace(status='failed', payment_metadata=None))
    assert payment_hidden_from_admin_history(SimpleNamespace(status='canceled', payment_metadata=None))
    assert payment_hidden_from_admin_history(SimpleNamespace(status='voided', payment_metadata={}))


def test_shows_succeeded_and_pending():
    assert not payment_hidden_from_admin_history(
        SimpleNamespace(status='succeeded', payment_metadata=None)
    )
    assert not payment_hidden_from_admin_history(
        SimpleNamespace(status='pending', payment_metadata=None)
    )
    assert not payment_hidden_from_admin_history(
        SimpleNamespace(status='partially_refunded', payment_metadata=None)
    )


def test_hides_metadata_flag_even_if_pending():
    assert payment_hidden_from_admin_history(
        SimpleNamespace(
            status='pending',
            payment_metadata={'hidden_from_admin_history': True},
        )
    )
