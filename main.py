from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import razorpay
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from razorpay.errors import SignatureVerificationError

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="RozPay", description="A Razorpay Checkout demo")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@dataclass(frozen=True)
class Settings:
    key_id: str
    key_secret: str
    product_name: str
    product_description: str


def get_settings() -> Settings:
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        raise HTTPException(
            status_code=503,
            detail="Razorpay is not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.",
        )

    return Settings(
        key_id=key_id,
        key_secret=key_secret,
        product_name=os.getenv("PRODUCT_NAME", "RozPay Demo Product").strip() or "RozPay Demo Product",
        product_description=os.getenv(
            "PRODUCT_DESCRIPTION", "A secure checkout powered by Razorpay."
        ).strip(),
    )


def get_gateway(settings: Settings) -> razorpay.Client:
    return razorpay.Client(auth=(settings.key_id, settings.key_secret))


class PaymentVerification(BaseModel):
    razorpay_order_id: str = Field(min_length=1, max_length=128)
    razorpay_payment_id: str = Field(min_length=1, max_length=128)
    razorpay_signature: str = Field(min_length=1, max_length=512)


class CreateOrderRequest(BaseModel):
    amount_rupees: Decimal = Field(gt=0, max_digits=8, decimal_places=2)


@app.get("/")
def payment_page() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/payment/success")
def payment_success_page(payment_id: str = Query(min_length=1, max_length=128)) -> FileResponse:
    settings = get_settings()
    try:
        payment_details = get_gateway(settings).payment.fetch(payment_id)
    except Exception as exc:
        logger.exception("Could not confirm payment before showing success page")
        raise HTTPException(status_code=502, detail="Could not confirm payment. Please retry shortly.") from exc

    if payment_details.get("id") != payment_id or payment_details.get("status") != "captured":
        raise HTTPException(status_code=409, detail="Payment is not confirmed as captured.")

    return FileResponse(BASE_DIR / "static" / "payment-success.html")


@app.get("/payment/failure")
def payment_failure_page() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "payment-failure.html")


@app.get("/api/config")
def public_config() -> dict[str, str | int]:
    settings = get_settings()
    return {
        "key_id": settings.key_id,
        "product_name": settings.product_name,
        "product_description": settings.product_description,
        "currency": "INR",
    }


@app.post("/api/create-order")
def create_order(request: CreateOrderRequest) -> dict[str, str | int]:
    settings = get_settings()
    amount_paise = int(request.amount_rupees * 100)
    if not 100 <= amount_paise <= 10_000_000:
        raise HTTPException(status_code=422, detail="Enter an amount from ₹1.00 to ₹100,000.00.")

    client = get_gateway(settings)
    try:
        order = client.order.create(
            data={
                "amount": amount_paise,
                "currency": "INR",
                "receipt": f"rozpay_{uuid4().hex[:24]}",
                "notes": {"product": settings.product_name},
            }
        )
    except Exception as exc:
        logger.exception("Razorpay order creation failed")
        raise HTTPException(status_code=502, detail="Could not create a payment order.") from exc

    if order.get("amount") != amount_paise or order.get("currency") != "INR":
        raise HTTPException(status_code=502, detail="Razorpay returned an order with an unexpected amount.")

    return {
        "order_id": order["id"],
        "amount_paise": amount_paise,
        "currency": "INR",
        "key_id": settings.key_id,
        "product_name": settings.product_name,
        "product_description": settings.product_description,
    }


@app.post("/api/verify-payment")
def verify_payment(payment: PaymentVerification) -> dict[str, str]:
    settings = get_settings()
    client = get_gateway(settings)
    signature_data = {
        "razorpay_order_id": payment.razorpay_order_id,
        "razorpay_payment_id": payment.razorpay_payment_id,
        "razorpay_signature": payment.razorpay_signature,
    }
    try:
        client.utility.verify_payment_signature(signature_data)
    except SignatureVerificationError as exc:
        raise HTTPException(status_code=400, detail="Payment signature could not be verified.") from exc
    except Exception as exc:
        logger.exception("Razorpay signature verification failed unexpectedly")
        raise HTTPException(status_code=502, detail="Payment verification is temporarily unavailable.") from exc

    try:
        payment_details = client.payment.fetch(payment.razorpay_payment_id)
        order_details = client.order.fetch(payment.razorpay_order_id)
    except Exception as exc:
        logger.exception("Could not fetch Razorpay payment status")
        raise HTTPException(status_code=502, detail="Could not confirm payment status yet.") from exc

    if payment_details.get("order_id") != payment.razorpay_order_id:
        raise HTTPException(status_code=400, detail="Payment does not match the supplied order.")
    if (
        payment_details.get("amount") != order_details.get("amount")
        or payment_details.get("currency") != "INR"
        or order_details.get("currency") != "INR"
    ):
        raise HTTPException(status_code=400, detail="Payment amount or currency does not match this order.")
    if payment_details.get("status") != "captured":
        raise HTTPException(status_code=409, detail="Payment is not captured yet. Please check again shortly.")

    return {"status": "success", "payment_id": payment.razorpay_payment_id}
