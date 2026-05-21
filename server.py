import os
from pathlib import Path

import stripe
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")


def parse_price_cents(raw: str) -> int:
    """Accept cents (399), dollars (3.99), or European format (3,99)."""
    value = (raw or "999").strip()
    if not value:
        return 999
    if "," in value and "." not in value and value.count(",") == 1:
        value = value.replace(",", ".")
    else:
        value = value.replace(",", "")
    if "." in value:
        return int(round(float(value) * 100))
    return int(value)


PRICE_CENTS = parse_price_cents(os.environ.get("STRIPE_PRICE_CENTS", "999"))
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
PORT = int(os.environ.get("PORT", "8000"))

FORM_FIELDS = [
    "plate_owner_name",
    "plate_renter_name",
    "agreement_date",
    "plate_number",
    "start_date",
    "end_date",
    "rent_amount",
]

app = Flask(__name__, static_folder=str(PUBLIC_DIR), static_url_path="")


@app.route("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(PUBLIC_DIR, filename)


@app.get("/api/config")
def api_config():
    return jsonify(
        {
            "publishableKey": os.environ.get("STRIPE_PUBLISHABLE_KEY", ""),
            "priceCents": PRICE_CENTS,
            "priceLabel": f"${PRICE_CENTS / 100:,.2f}",
            "paymentsEnabled": bool(stripe.api_key),
        }
    )


@app.post("/api/create-checkout-session")
def create_checkout_session():
    if not stripe.api_key:
        return jsonify({"error": "Stripe is not configured on the server."}), 500

    payload = request.get_json(silent=True) or {}
    missing = [field for field in FORM_FIELDS if not str(payload.get(field, "")).strip()]
    if missing:
        return jsonify({"error": "Please fill all required fields before payment.", "missing": missing}), 400

    metadata = {
        field: str(payload.get(field, "")).strip()[:500]
        for field in FORM_FIELDS
    }

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": PRICE_CENTS,
                        "product_data": {
                            "name": "Plate Rental Agreement PDF",
                            "description": "Official downloadable rental agreement PDF",
                        },
                    },
                    "quantity": 1,
                }
            ],
            success_url=f"{BASE_URL}/?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/?canceled=1",
            metadata=metadata,
        )
    except stripe.error.StripeError as exc:
        return jsonify({"error": str(exc.user_message or exc)}), 400

    return jsonify({"url": session.url})


@app.get("/api/verify-payment")
def verify_payment():
    if not stripe.api_key:
        return jsonify({"error": "Stripe is not configured on the server."}), 500

    session_id = request.args.get("session_id", "").strip()
    if not session_id:
        return jsonify({"paid": False, "error": "Missing session_id"}), 400

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError as exc:
        return jsonify({"paid": False, "error": str(exc.user_message or exc)}), 400

    paid = session.payment_status == "paid"
    metadata = {field: session.metadata.get(field, "") for field in FORM_FIELDS} if paid else {}

    return jsonify({"paid": paid, "metadata": metadata})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)
