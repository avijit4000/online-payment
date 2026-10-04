from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import razorpay
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path as ApiPath, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from razorpay.errors import SignatureVerificationError

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_phonepe_token_lock = threading.Lock()
_phonepe_cached_token = ""
_phonepe_cached_context: tuple[str, str, str, str] | None = None
_phonepe_token_expires_at = 0.0

app = FastAPI(title="RozPay", description="A Razorpay Checkout demo")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@dataclass(frozen=True)
class Settings:
    razorpay_key_id: str
    razorpay_key_secret: str
    phonepe_client_id: str
    phonepe_client_secret: str
    phonepe_client_version: str
    phonepe_environment: str
    product_name: str
    product_description: str


def get_settings() -> Settings:
    return Settings(
        razorpay_key_id=os.getenv("RAZORPAY_KEY_ID", "").strip(),
        razorpay_key_secret=os.getenv("RAZORPAY_KEY_SECRET", "").strip(),
        phonepe_client_id=os.getenv("PHONEPE_CLIENT_ID", "").strip(),
        phonepe_client_secret=os.getenv("PHONEPE_CLIENT_SECRET", "").strip(),
        phonepe_client_version=os.getenv("PHONEPE_CLIENT_VERSION", "1").strip(),
        phonepe_environment=os.getenv("PHONEPE_ENVIRONMENT", "sandbox").strip().lower(),
        product_name=os.getenv("PRODUCT_NAME", "RozPay Demo Product").strip() or "RozPay Demo Product",
        product_description=os.getenv(
            "PRODUCT_DESCRIPTION", "A secure checkout powered by Razorpay."
        ).strip(),
    )


def get_gateway(settings: Settings) -> razorpay.Client:
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=503, detail="Razorpay is not configured.")
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


def phonepe_base_url(settings: Settings) -> str:
    if settings.phonepe_environment == "sandbox":
        return "https://api-preprod.phonepe.com/apis/pg-sandbox"
    if settings.phonepe_environment == "production":
        return "https://api.phonepe.com/apis/pg"
    raise HTTPException(status_code=500, detail="PHONEPE_ENVIRONMENT must be sandbox or production.")


def phonepe_access_token(settings: Settings) -> str:
    global _phonepe_cached_token, _phonepe_cached_context, _phonepe_token_expires_at
    if not settings.phonepe_client_id or not settings.phonepe_client_secret:
        raise HTTPException(status_code=503, detail="PhonePe is not configured.")
    auth_context = (
        settings.phonepe_environment,
        settings.phonepe_client_id,
        settings.phonepe_client_secret,
        settings.phonepe_client_version,
    )
    with _phonepe_token_lock:
        if _phonepe_cached_token and _phonepe_cached_context == auth_context and time.time() < _phonepe_token_expires_at - 60:
            return _phonepe_cached_token

        token_url = (
            "https://api-preprod.phonepe.com/apis/pg-sandbox/v1/oauth/token"
            if settings.phonepe_environment == "sandbox"
            else "https://api.phonepe.com/apis/identity-manager/v1/oauth/token"
            if settings.phonepe_environment == "production"
            else None
        )
        if not token_url:
            raise HTTPException(status_code=500, detail="PHONEPE_ENVIRONMENT must be sandbox or production.")
    try:
        response = httpx.post(
            token_url,
            data={
                "client_id": settings.phonepe_client_id,
                "client_version": settings.phonepe_client_version,
                "client_secret": settings.phonepe_client_secret,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        response.raise_for_status()
        token_data = response.json()
        token = token_data.get("access_token")
        if not token:
            raise ValueError("PhonePe token response did not contain an access token.")
        expires_at = token_data.get("expires_at") or (time.time() + token_data.get("expires_in", 300))
        with _phonepe_token_lock:
            _phonepe_cached_token = str(token)
            _phonepe_cached_context = auth_context
            _phonepe_token_expires_at = float(expires_at)
        return str(token)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PhonePe authentication failed")
        raise HTTPException(status_code=502, detail="Could not authenticate with PhonePe.") from exc


def phonepe_request(settings: Settings, method: str, path: str, **kwargs) -> dict:
    token = phonepe_access_token(settings)
    try:
        response = httpx.request(
            method,
            f"{phonepe_base_url(settings)}{path}",
            headers={"Authorization": f"O-Bearer {token}", "Content-Type": "application/json"},
            timeout=20,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.exception("PhonePe API request failed")
        raise HTTPException(status_code=502, detail="PhonePe payment service request failed.") from exc


def phonepe_payment_summary(settings: Settings, merchant_order_id: str) -> dict:
    result = phonepe_request(
        settings,
        "GET",
        f"/checkout/v2/order/{merchant_order_id}/status",
        params={"details": "false", "errorContext": "true"},
    )
    payment_details = result.get("paymentDetails") or []
    latest_payment = payment_details[-1] if payment_details else {}
    error_context = result.get("errorContext") or {}
    return {
        "state": str(result.get("state", "PENDING")).upper(),
        "payment_id": latest_payment.get("transactionId") or result.get("paymentId"),
        "reason": error_context.get("description") or latest_payment.get("errorCode") or latest_payment.get("detailedErrorCode") or result.get("errorCode"),
    }


class PaymentVerification(BaseModel):
    razorpay_order_id: str = Field(min_length=1, max_length=128)
    razorpay_payment_id: str = Field(min_length=1, max_length=128)
    razorpay_signature: str = Field(min_length=1, max_length=512)


class CreateOrderRequest(BaseModel):
    amount_rupees: Decimal = Field(gt=0, max_digits=8, decimal_places=2)
    provider: str = Field(pattern="^(razorpay|phonepe)$")


def request_url_for_phonepe(request: Request, merchant_order_id: str) -> str:
    return f"{str(request.base_url).rstrip('/')}/payment/phonepe/return?merchant_order_id={merchant_order_id}"


@app.get("/")
def payment_page() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/payment/success")
def payment_success_page(
    payment_id: str | None = Query(default=None, max_length=128),
    provider: str = Query(default="razorpay", pattern="^(razorpay|phonepe)$"),
    merchant_order_id: str | None = Query(default=None, max_length=64, pattern="^rozpay_[a-f0-9]{32}$"),
) -> FileResponse:
    settings = get_settings()
    if provider == "phonepe":
        if not merchant_order_id or not payment_id:
            raise HTTPException(status_code=400, detail="PhonePe merchant order ID and payment ID are required.")
        summary = phonepe_payment_summary(settings, merchant_order_id)
        if summary["state"] != "COMPLETED" or not summary["payment_id"]:
            raise HTTPException(status_code=409, detail="PhonePe payment is not confirmed as completed.")
        if payment_id != summary["payment_id"]:
            raise HTTPException(status_code=400, detail="Payment ID does not match the PhonePe order.")
    else:
        if not payment_id:
            raise HTTPException(status_code=400, detail="Razorpay payment ID is required.")
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


@app.get("/payment/phonepe/return")
def phonepe_return_page(merchant_order_id: str = Query(min_length=1, max_length=64, pattern="^rozpay_[a-f0-9]{32}$")) -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "phonepe-result.html")


@app.get("/api/config")
def public_config() -> dict[str, object]:
    settings = get_settings()
    return {
        "product_name": settings.product_name,
        "product_description": settings.product_description,
        "currency": "INR",
        "providers": {
            "razorpay": bool(settings.razorpay_key_id and settings.razorpay_key_secret),
            "phonepe": bool(settings.phonepe_client_id and settings.phonepe_client_secret),
        },
        "razorpay_key_id": settings.razorpay_key_id if settings.razorpay_key_id and settings.razorpay_key_secret else None,
    }


@app.post("/api/create-order")
def create_order(payload: CreateOrderRequest, http_request: Request) -> dict[str, str | int]:
    settings = get_settings()
    amount_paise = int(payload.amount_rupees * 100)
    if not 100 <= amount_paise <= 10_000_000:
        raise HTTPException(status_code=422, detail="Enter an amount from ₹1.00 to ₹100,000.00.")

    if payload.provider == "razorpay":
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
            raise HTTPException(status_code=502, detail="Could not create a Razorpay payment order.") from exc

        if order.get("amount") != amount_paise or order.get("currency") != "INR":
            raise HTTPException(status_code=502, detail="Razorpay returned an order with an unexpected amount.")

        return {
            "provider": "razorpay",
            "order_id": order["id"],
            "amount_paise": amount_paise,
            "currency": "INR",
            "key_id": settings.razorpay_key_id,
            "product_name": settings.product_name,
            "product_description": settings.product_description,
        }

    merchant_order_id = f"rozpay_{uuid4().hex}"
    redirect_url = request_url_for_phonepe(http_request, merchant_order_id)
    result = phonepe_request(
        settings,
        "POST",
        "/checkout/v2/pay",
        json={
            "merchantOrderId": merchant_order_id,
            "amount": amount_paise,
            "expireAfter": 1200,
            "metaInfo": {"udf1": settings.product_name[:256]},
            "paymentFlow": {
                "type": "PG_CHECKOUT",
                "merchantUrls": {"redirectUrl": redirect_url},
            },
        },
    )
    checkout_url = result.get("redirectUrl")
    if not checkout_url:
        logger.error("PhonePe checkout response omitted redirectUrl")
        raise HTTPException(status_code=502, detail="PhonePe did not return a checkout URL.")
    return {
        "provider": "phonepe",
        "merchant_order_id": merchant_order_id,
        "redirect_url": checkout_url,
        "amount_paise": amount_paise,
        "currency": "INR",
    }


@app.get("/api/phonepe/status/{merchant_order_id}")
def phonepe_order_status(
    merchant_order_id: str = ApiPath(min_length=1, max_length=64, pattern="^rozpay_[a-f0-9]{32}$"),
) -> dict[str, str | None]:
    settings = get_settings()
    if not settings.phonepe_client_id or not settings.phonepe_client_secret:
        raise HTTPException(status_code=503, detail="PhonePe is not configured.")
    return phonepe_payment_summary(settings, merchant_order_id)


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
