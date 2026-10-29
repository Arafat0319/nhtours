import math
import stripe


def init_stripe(secret_key):
    stripe.api_key = secret_key


def _normalize_metadata(metadata):
    if not metadata:
        return {}
    normalized = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple)):
            normalized[key] = str(value)
        else:
            normalized[key] = str(value)
    return normalized


def retrieve_payment_method_card_details(payment_method_id):
    try:
        payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
    except Exception:
        return "unknown", "unknown"

    pm_type = getattr(payment_method, "type", None) or "unknown"
    if pm_type == "us_bank_account":
        return "ach", "us_bank"

    card = getattr(payment_method, "card", None)
    if not card:
        return "unknown", "unknown"

    return card.get("funding", "unknown"), card.get("brand", "unknown")


def retrieve_payment_method_funding(payment_method_id):
    funding, _brand = retrieve_payment_method_card_details(payment_method_id)
    return funding


def calculate_fee(base_amount, funding, brand):
    # Match live site: all cards 2.9%; ACH $0.
    funding = (funding or "").strip().lower()
    brand = (brand or "").strip().lower()
    if funding == "ach" or brand == "us_bank":
        return 0
    return int(math.ceil(int(base_amount or 0) * 0.029))


def create_or_update_payment_intent(order_id, amount, currency, metadata, payment_intent_id=None):
    normalized_metadata = _normalize_metadata(metadata)
    if payment_intent_id:
        payment_intent = stripe.PaymentIntent.modify(
            payment_intent_id,
            amount=amount,
            currency=currency,
            metadata=normalized_metadata,
        )
        return {
            "id": payment_intent.id,
            "client_secret": payment_intent.client_secret,
        }

    payment_intent = stripe.PaymentIntent.create(
        amount=amount,
        currency=currency,
        payment_method_types=["card"],
        metadata=normalized_metadata,
    )
    return {
        "id": payment_intent.id,
        "client_secret": payment_intent.client_secret,
    }


def verify_webhook_event(payload, sig_header, webhook_secret):
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        return event
    except Exception:
        return None


def retrieve_payment_intent(payment_intent_id):
    try:
        return stripe.PaymentIntent.retrieve(payment_intent_id)
    except Exception:
        return None


def calculate_tax(_amount, _currency, _address):
    return 0
