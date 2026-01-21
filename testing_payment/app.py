import os
import uuid
import logging
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from dotenv import load_dotenv
from services.order_store import (
    create_order,
    get_order,
    update_order_selection,
    set_order_payment_intent,
    set_order_status,
    record_quote,
    get_order_status,
)
from services.stripe_service import (
    init_stripe,
    retrieve_payment_method_card_details,
    calculate_fee,
    create_or_update_payment_intent,
    verify_webhook_event,
    retrieve_payment_intent,
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("APP_SECRET_KEY", "dev-secret-key")
    app.config["STRIPE_SECRET_KEY"] = os.getenv("STRIPE_SECRET_KEY")
    app.config["STRIPE_PUBLISHABLE_KEY"] = os.getenv("STRIPE_PUBLISHABLE_KEY")
    app.config["STRIPE_WEBHOOK_SECRET"] = os.getenv("STRIPE_WEBHOOK_SECRET")

    init_stripe(app.config["STRIPE_SECRET_KEY"])
    logging.basicConfig(level=logging.INFO)

    def build_order_metadata(order, extra=None):
        summary = order.get("summary") or {}
        package = summary.get("package") or {}
        addons = order.get("addons") or {}
        addons_compact = ",".join(f"{addon_id}:{qty}" for addon_id, qty in addons.items())
        metadata = {
            "env": "test",
            "source": "testing_payment",
            "payment_flow": "payment_intent",
            "payment_plan": "full",
            "booking_id": order.get("order_id"),
            "trip_id": order.get("trip_id"),
            "trip_title": "Mock Trip",
            "trip_slug": "mock-trip",
            "client_id": "mock_client_001",
            "buyer_email": "test@example.com",
            "buyer_name": "Test User",
            "package_id": order.get("package_id"),
            "package_name": package.get("name"),
            "package_qty": order.get("package_qty"),
            "participants": order.get("participants"),
            "addons": addons_compact,
            "base_amount": order.get("base_amount"),
        }
        if extra:
            metadata.update(extra)
        return metadata

    @app.route("/")
    def index():
        return redirect(url_for("cart"))

    @app.route("/cart", methods=["GET", "POST"])
    def cart():
        order_id = session.get("order_id")
        if not order_id:
            order_id = create_order()
            session["order_id"] = order_id

        order = get_order(order_id)
        if not order:
            order_id = create_order()
            session["order_id"] = order_id
            order = get_order(order_id)
        if request.method == "POST":
            selection = {
                "package_id": request.form.get("package_id"),
                "package_qty": int(request.form.get("package_qty", "1")),
                "addon_ids": request.form.getlist("addon_id"),
                "addon_qty_map": {
                    addon_id: request.form.get(f"addon_qty_{addon_id}", "1")
                    for addon_id in request.form.getlist("addon_id")
                },
                "participants": int(request.form.get("participants", "1")),
            }
            update_order_selection(order_id, selection)
            return redirect(url_for("checkout"))

        return render_template(
            "cart.html",
            order=order,
        )

    @app.route("/checkout")
    def checkout():
        order_id = session.get("order_id")
        if not order_id:
            return redirect(url_for("cart"))

        order = get_order(order_id)
        if not order:
            order_id = create_order()
            session["order_id"] = order_id
            order = get_order(order_id)

        set_order_payment_intent(order_id, None)
        checkout_metadata = build_order_metadata(
            order,
            {
                "payment_step": "checkout_init",
            },
        )
        payment_intent = create_or_update_payment_intent(
            order_id=order_id,
            amount=order["base_amount"],
            currency="usd",
            metadata=checkout_metadata,
        )
        set_order_payment_intent(order_id, payment_intent["id"])

        return render_template(
            "checkout.html",
            order=order,
            client_secret=payment_intent["client_secret"],
            publishable_key=app.config["STRIPE_PUBLISHABLE_KEY"],
        )

    @app.route("/success")
    def success():
        order_id = request.args.get("order_id") or session.get("order_id")
        status = get_order_status(order_id) if order_id else "UNKNOWN"
        return render_template("success.html", order_id=order_id, status=status)

    @app.route("/failed")
    def failed():
        order_id = request.args.get("order_id") or session.get("order_id")
        status = get_order_status(order_id) if order_id else "FAILED"
        return render_template("failed.html", order_id=order_id, status=status)

    @app.route("/api/order")
    def api_order():
        order_id = session.get("order_id")
        order = get_order(order_id) if order_id else None
        if not order:
            return jsonify({"error": "order_not_found"}), 404

        return jsonify(
            {
                "order_id": order_id,
                "summary": order["summary"],
                "base_amount": order["base_amount"],
                "currency": "usd",
            }
        )

    @app.route("/api/quote", methods=["POST"])
    def api_quote():
        data = request.get_json(silent=True) or {}
        order_id = data.get("order_id") or session.get("order_id")
        payment_method_id = data.get("payment_method_id")
        billing_address = data.get("billing_address")

        if not order_id or not payment_method_id:
            return jsonify({"error": "missing_parameters"}), 400

        order = get_order(order_id)
        if not order:
            return jsonify({"error": "order_not_found"}), 404

        funding, brand = retrieve_payment_method_card_details(payment_method_id)
        fee = calculate_fee(order["base_amount"], funding, brand)
        tax_amount = 0
        final_amount = order["base_amount"] + fee + tax_amount

        record_quote(order_id, payment_method_id, funding, brand, fee, tax_amount, final_amount)
        app.logger.info(
            "Quote computed order_id=%s funding=%s brand=%s base=%s fee=%s final=%s",
            order_id,
            funding,
            brand,
            order["base_amount"],
            fee,
            final_amount,
        )

        return jsonify(
            {
                "funding": funding,
                "base_amount": order["base_amount"],
                "fee": fee,
                "tax_amount": tax_amount,
                "final_amount": final_amount,
            }
        )

    @app.route("/api/payment-intent", methods=["POST"])
    def api_payment_intent():
        data = request.get_json(silent=True) or {}
        order_id = data.get("order_id") or session.get("order_id")
        if not order_id:
            return jsonify({"error": "missing_order_id"}), 400

        order = get_order(order_id)
        if not order:
            return jsonify({"error": "order_not_found"}), 404

        funding = order.get("last_quote", {}).get("funding", "unknown")
        brand = order.get("last_quote", {}).get("brand", "unknown")
        payment_method_id = order.get("last_quote", {}).get("payment_method_id")
        fee = calculate_fee(order["base_amount"], funding, brand)
        tax_amount = order.get("last_quote", {}).get("tax_amount", 0)
        final_amount = order["base_amount"] + fee + tax_amount

        quote_metadata = build_order_metadata(
            order,
            {
                "payment_step": "quote_update",
                "funding": funding,
                "brand": brand,
                "fee": fee,
                "tax_amount": tax_amount,
                "final_amount": final_amount,
                "payment_method_id": payment_method_id,
            },
        )
        payment_intent = create_or_update_payment_intent(
            order_id=order_id,
            amount=final_amount,
            currency="usd",
            metadata=quote_metadata,
            payment_intent_id=order.get("payment_intent_id"),
        )
        set_order_payment_intent(order_id, payment_intent["id"])

        return jsonify(
            {
                "client_secret": payment_intent["client_secret"],
                "payment_intent_id": payment_intent["id"],
                "final_amount": final_amount,
            }
        )

    @app.route("/api/stripe/webhook", methods=["POST"])
    def stripe_webhook():
        payload = request.data
        sig_header = request.headers.get("Stripe-Signature")
        event = verify_webhook_event(
            payload=payload,
            sig_header=sig_header,
            webhook_secret=app.config["STRIPE_WEBHOOK_SECRET"],
        )

        if event is None:
            return jsonify({"error": "invalid_signature"}), 400

        event_type = event["type"]
        data_object = event["data"]["object"]
        app.logger.info("Webhook received type=%s", event_type)

        if event_type == "payment_intent.succeeded":
            order_id = data_object.get("metadata", {}).get("booking_id")
            if order_id:
                set_order_status(order_id, "PAID")
                app.logger.info("Order marked PAID order_id=%s", order_id)
        elif event_type == "payment_intent.payment_failed":
            order_id = data_object.get("metadata", {}).get("booking_id")
            if order_id:
                set_order_status(order_id, "FAILED")
                app.logger.info("Order marked FAILED order_id=%s", order_id)

        return jsonify({"status": "ok"})

    @app.route("/api/stripe/payment-intent/<payment_intent_id>")
    def api_stripe_payment_intent(payment_intent_id):
        payment_intent = retrieve_payment_intent(payment_intent_id)
        if not payment_intent:
            return jsonify({"error": "payment_intent_not_found"}), 404

        return jsonify(
            {
                "id": payment_intent.get("id"),
                "status": payment_intent.get("status"),
                "amount": payment_intent.get("amount"),
                "currency": payment_intent.get("currency"),
                "payment_method": payment_intent.get("payment_method"),
                "metadata": payment_intent.get("metadata", {}),
            }
        )

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
