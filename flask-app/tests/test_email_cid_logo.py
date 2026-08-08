"""Brand logo CID inline attachment for SES raw email."""

from unittest.mock import MagicMock, patch

from app.utils import (
    EMAIL_BRAND_LOGO_CID,
    _email_brand_logo_url,
    send_email_via_ses,
)


def test_email_brand_logo_url_is_cid(app):
    with app.app_context():
        assert _email_brand_logo_url() == f'cid:{EMAIL_BRAND_LOGO_CID}'


def test_send_email_embeds_cid_logo(app):
    captured = {}

    def fake_send_raw_email(**kwargs):
        captured['raw'] = kwargs['RawMessage']['Data']
        return {'MessageId': 'test-msgid'}

    html = (
        '<!DOCTYPE html><html><body>'
        f'<img src="cid:{EMAIL_BRAND_LOGO_CID}" alt="logo">'
        '</body></html>'
    )

    with app.app_context():
        with patch('app.utils.boto3.client') as mock_client:
            ses = MagicMock()
            ses.send_raw_email.side_effect = fake_send_raw_email
            mock_client.return_value = ses
            ok, msg = send_email_via_ses(
                'noreply@nhtours.com',
                'guest@example.com',
                'CID logo test',
                html,
                'plain',
            )

    assert ok is True
    raw = captured['raw']
    assert isinstance(raw, (bytes, bytearray))
    assert b'Content-ID:' in raw
    assert EMAIL_BRAND_LOGO_CID.encode('ascii') in raw
    assert b'image/png' in raw
    assert b'nexus-horizons-email.png' in raw
    assert b'multipart/related' in raw


def test_send_email_cid_logo_with_pdf_attachment(app):
    captured = {}

    def fake_send_raw_email(**kwargs):
        captured['raw'] = kwargs['RawMessage']['Data']
        return {'MessageId': 'test-msgid-pdf'}

    html = f'<html><body><img src="cid:{EMAIL_BRAND_LOGO_CID}"></body></html>'
    pdf = b'%PDF-1.4 fake'

    with app.app_context():
        with patch('app.utils.boto3.client') as mock_client:
            ses = MagicMock()
            ses.send_raw_email.side_effect = fake_send_raw_email
            mock_client.return_value = ses
            ok, _ = send_email_via_ses(
                'noreply@nhtours.com',
                'guest@example.com',
                'CID + PDF',
                html,
                'plain',
                attachments=[{
                    'filename': 'receipt.pdf',
                    'content': pdf,
                    'mime_subtype': 'pdf',
                }],
            )

    assert ok is True
    raw = captured['raw']
    assert EMAIL_BRAND_LOGO_CID.encode('ascii') in raw
    assert b'receipt.pdf' in raw
    assert b'multipart/mixed' in raw
    assert b'multipart/related' in raw
    # PDF body is base64 in MIME
    assert b'JVBERi0xLjQgZmFrZQ==' in raw
