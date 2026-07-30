"""Generate Stripe-Signature and optionally POST to local webhook."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request


def sign(payload: str, secret: str) -> str:
    secret = secret.strip().strip('"').strip("'")
    # stripe-python 11+ HMAC uses the whsec_ string as UTF-8 (not base64-decoded)
    key = secret.encode("utf-8")
    t = int(time.time())
    mac = hmac.new(key, f"{t}.{payload}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def main() -> int:
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET") or os.environ.get(
        "E2E_STRIPE_WEBHOOK_SECRET"
    )
    if not secret:
        print("missing webhook secret", file=sys.stderr)
        return 2
    payload = sys.argv[1] if len(sys.argv) > 1 else json.dumps(
        {
            "id": "evt_probe",
            "object": "event",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_probe",
                    "object": "payment_intent",
                    "status": "succeeded",
                }
            },
        }
    )
    header = sign(payload, secret)
    if "--post" in sys.argv:
        base = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
        req = urllib.request.Request(
            f"{base}/webhooks/stripe",
            data=payload.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": header,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as r:
                print(r.status, r.read()[:300].decode("utf-8", "replace"))
        except Exception as e:
            body = getattr(e, "read", lambda: b"")()
            print("ERR", e, body[:300])
            return 1
    else:
        print(header)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
