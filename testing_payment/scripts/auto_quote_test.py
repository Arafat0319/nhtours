import json
import os
import sys
import urllib.request
from dotenv import load_dotenv
import stripe


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

API_BASE = os.getenv("TEST_API_BASE", "http://localhost:5000")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


def http_json(method, url, data=None):
    payload = None
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def create_payment_method(card_number):
    return stripe.PaymentMethod.create(
        type="card",
        card={
            "number": card_number,
            "exp_month": 12,
            "exp_year": 2030,
            "cvc": "123",
        },
    )


def main():
    if not stripe.api_key:
        print("缺少 STRIPE_SECRET_KEY，请先在 .env 中配置。")
        sys.exit(1)

    order = http_json("GET", f"{API_BASE}/api/order")
    order_id = order["order_id"]

    test_cards = {
        "credit": "4242424242424242",
        "debit": "4000566655665556",
        "prepaid": "5105105105105100",
    }

    for label, card_number in test_cards.items():
        pm = create_payment_method(card_number)
        quote = http_json(
            "POST",
            f"{API_BASE}/api/quote",
            {"order_id": order_id, "payment_method_id": pm["id"]},
        )
        print(
            f"[{label}] funding={quote.get('funding')} fee={quote.get('fee')} final={quote.get('final_amount')}"
        )

    payment_intent = http_json(
        "POST",
        f"{API_BASE}/api/payment-intent",
        {"order_id": order_id},
    )
    print(f"PI ready id={payment_intent.get('payment_intent_id')}")


if __name__ == "__main__":
    main()
