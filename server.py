import base64
import json
import logging
import os
import re
import smtplib
import threading
import urllib.error
import urllib.request
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import fitz
import stripe
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
TEMPLATE_PDF = PUBLIC_DIR / "agreement-template.pdf"

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USER or "Singh Documents <onboarding@resend.dev>")
SMTP_TIMEOUT = int(os.environ.get("SMTP_TIMEOUT", "12"))
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "").lower() in {"1", "true", "yes"}


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

PDF_FIELDS = FORM_FIELDS + ["owner_signature_name", "renter_signature_name"]
CHECKOUT_FIELDS = FORM_FIELDS + ["customer_email"]


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match((value or "").strip()))


def read_metadata_value(meta, field: str) -> str:
    try:
        if field in meta:
            return str(meta[field])
    except (KeyError, TypeError, AttributeError):
        pass
    return ""


def extract_checkout_metadata(session) -> dict:
    """Read checkout metadata safely from Stripe SDK objects."""
    result = {field: "" for field in CHECKOUT_FIELDS}
    meta = session.get("metadata") if hasattr(session, "get") else getattr(session, "metadata", None)
    if not meta:
        return result

    for field in CHECKOUT_FIELDS:
        result[field] = read_metadata_value(meta, field)
    return result


def build_pdf_bytes(form_data: dict) -> bytes:
    data = dict(form_data)
    data["owner_signature_name"] = data.get("plate_owner_name", "")
    data["renter_signature_name"] = data.get("plate_renter_name", "")

    doc = fitz.open(TEMPLATE_PDF)
    for page in doc:
        for widget in page.widgets() or []:
            name = widget.field_name
            if name and name in data:
                widget.field_value = str(data.get(name, ""))
                widget.update()

    pdf_bytes = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return pdf_bytes


def email_is_configured() -> bool:
    if RESEND_API_KEY and EMAIL_FROM:
        return True
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD and EMAIL_FROM)


def email_provider() -> str:
    if RESEND_API_KEY:
        return "resend"
    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        return "smtp"
    return "none"


def build_email_text(form_data: dict) -> str:
    owner = form_data.get("plate_owner_name", "")
    renter = form_data.get("plate_renter_name", "")
    plate = form_data.get("plate_number", "")
    return (
        "Thank you for your payment.\n\n"
        "Attached is your rental agreement PDF.\n\n"
        f"Owner: {owner}\n"
        f"Renter: {renter}\n"
        f"Plate: {plate}\n\n"
        "— Singh Documents"
    )


def send_pdf_email_resend(to_email: str, pdf_bytes: bytes, form_data: dict) -> None:
    payload = {
        "from": EMAIL_FROM,
        "to": [to_email],
        "subject": "Your Plate Rental Agreement PDF",
        "text": build_email_text(form_data),
        "attachments": [
            {
                "filename": "Plate-Rental-Agreement.pdf",
                "content": base64.b64encode(pdf_bytes).decode("ascii"),
            }
        ],
    }
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "singhdocuments-pdf/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status >= 300:
                raise RuntimeError(f"Resend API returned status {response.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        message = body
        try:
            payload = json.loads(body)
            message = payload.get("message", body)
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"Resend API HTTP {exc.code}: {message}") from exc


def send_pdf_email_smtp(to_email: str, pdf_bytes: bytes, form_data: dict) -> None:
    message = MIMEMultipart()
    message["Subject"] = "Your Plate Rental Agreement PDF"
    message["From"] = EMAIL_FROM
    message["To"] = to_email
    message.attach(MIMEText(build_email_text(form_data), "plain"))

    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename="Plate-Rental-Agreement.pdf")
    message.attach(attachment)

    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(message)
        return

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(message)


def send_pdf_email(to_email: str, pdf_bytes: bytes, form_data: dict) -> None:
    # Render blocks outbound SMTP; use Resend HTTPS API in production.
    if RESEND_API_KEY:
        send_pdf_email_resend(to_email, pdf_bytes, form_data)
        return
    send_pdf_email_smtp(to_email, pdf_bytes, form_data)


def mark_email_sent(session_id: str, metadata: dict) -> None:
    existing_meta = {field: str(metadata.get(field, ""))[:500] for field in CHECKOUT_FIELDS if metadata.get(field)}
    existing_meta["email_sent"] = "1"
    stripe.checkout.Session.modify(session_id, metadata=existing_meta)


def email_delivery_job(session_id: str, email: str, metadata: dict) -> None:
    try:
        pdf_bytes = build_pdf_bytes(metadata)
        send_pdf_email(email, pdf_bytes, metadata)
        mark_email_sent(session_id, metadata)
        logging.info("PDF email sent to %s for session %s", email, session_id)
    except Exception:
        logging.exception("PDF email failed for session %s", session_id)


def maybe_send_paid_email(session_id: str, session, metadata: dict) -> dict:
    """Queue PDF email delivery without blocking payment verification."""
    email = metadata.get("customer_email", "").strip()
    if not email:
        return {"emailSent": False, "emailError": "Missing customer email."}

    if metadata.get("email_sent") == "1":
        return {"emailSent": True, "emailNote": "Already sent."}

    if not email_is_configured():
        return {"emailSent": False, "emailError": "Email service is not configured on server."}

    thread = threading.Thread(
        target=email_delivery_job,
        args=(session_id, email, dict(metadata)),
        daemon=True,
    )
    thread.start()
    return {
        "emailSent": "pending",
        "emailMessage": "Your PDF is being emailed now. Check inbox and spam in a few minutes.",
    }


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
            "emailEnabled": email_is_configured(),
            "emailProvider": email_provider(),
        }
    )


@app.post("/api/create-checkout-session")
def create_checkout_session():
    if not stripe.api_key:
        return jsonify({"error": "Stripe is not configured on the server."}), 500

    payload = request.get_json(silent=True) or {}
    missing = [field for field in FORM_FIELDS if not str(payload.get(field, "")).strip()]
    customer_email = str(payload.get("customer_email", "")).strip()

    if missing:
        return jsonify({"error": "Please fill all required fields before payment.", "missing": missing}), 400
    if not is_valid_email(customer_email):
        return jsonify({"error": "Please enter a valid email address."}), 400

    metadata = {
        field: str(payload.get(field, "")).strip()[:500]
        for field in CHECKOUT_FIELDS
    }
    metadata["customer_email"] = customer_email[:500]

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            customer_email=customer_email,
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
    metadata = extract_checkout_metadata(session) if paid else {}

    response = {"paid": paid, "metadata": metadata}
    if paid:
        response.update(maybe_send_paid_email(session_id, session, metadata))

    return jsonify(response)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)
