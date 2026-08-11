"""Receipt email claim (status vs webhook race)."""
from datetime import datetime

from app import db
from app.models import Payment
from app.routes import claim_receipt_email_send, release_receipt_email_claim


def test_claim_receipt_email_only_once(app):
    with app.app_context():
        p = Payment(
            amount=10.0,
            status='succeeded',
            paid_at=datetime.utcnow(),
            currency='USD',
        )
        db.session.add(p)
        db.session.commit()
        pid = p.id

        assert claim_receipt_email_send(p) is True
        db.session.expire_all()
        p2 = Payment.query.get(pid)
        assert p2.receipt_email_sent_at is not None
        assert claim_receipt_email_send(p2) is False

        release_receipt_email_claim(p2)
        db.session.expire_all()
        p3 = Payment.query.get(pid)
        assert p3.receipt_email_sent_at is None
        assert claim_receipt_email_send(p3) is True

        db.session.delete(Payment.query.get(pid))
        db.session.commit()
