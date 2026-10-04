from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
PAYMENT = {
    "razorpay_order_id": "order_123",
    "razorpay_payment_id": "pay_123",
    "razorpay_signature": "signed_value",
}


def set_test_credentials(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_public")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "test_secret")


def set_phonepe_credentials(monkeypatch):
    monkeypatch.setenv("PHONEPE_CLIENT_ID", "phonepe_test_client")
    monkeypatch.setenv("PHONEPE_CLIENT_SECRET", "phonepe_test_secret")
    monkeypatch.setenv("PHONEPE_CLIENT_VERSION", "1")
    monkeypatch.setenv("PHONEPE_ENVIRONMENT", "sandbox")


def test_payment_page_is_served():
    response = client.get("/")

    assert response.status_code == 200
    assert "Order summary" in response.text


def test_success_page_requires_captured_razorpay_payment(monkeypatch):
    set_test_credentials(monkeypatch)

    class FakePayment:
        def fetch(self, payment_id):
            assert payment_id == "pay_captured"
            return {"id": payment_id, "status": "captured"}

    class FakeGateway:
        payment = FakePayment()

    monkeypatch.setattr(main, "get_gateway", lambda _settings: FakeGateway())
    response = client.get("/payment/success?payment_id=pay_captured")

    assert response.status_code == 200
    assert "Payment successful!" in response.text


def test_success_page_does_not_serve_for_uncaptured_payment(monkeypatch):
    set_test_credentials(monkeypatch)

    class FakePayment:
        def fetch(self, _payment_id):
            return {"id": "pay_pending", "status": "authorized"}

    class FakeGateway:
        payment = FakePayment()

    monkeypatch.setattr(main, "get_gateway", lambda _settings: FakeGateway())
    response = client.get("/payment/success?payment_id=pay_pending")

    assert response.status_code == 409


def test_payment_failure_page_is_served():
    response = client.get("/payment/failure?reason=declined")

    assert response.status_code == 200
    assert "couldn’t complete your payment" in response.text


def test_config_shows_disabled_providers_when_missing_credentials(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    monkeypatch.delenv("PHONEPE_CLIENT_ID", raising=False)
    monkeypatch.delenv("PHONEPE_CLIENT_SECRET", raising=False)

    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["providers"] == {"razorpay": False, "phonepe": False}


def test_config_returns_public_settings_but_not_secret(monkeypatch):
    set_test_credentials(monkeypatch)
    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["razorpay_key_id"] == "rzp_test_public"
    assert response.json()["providers"]["razorpay"] is True
    assert "test_secret" not in response.text


def test_create_order_uses_validated_customer_amount_in_paise(monkeypatch):
    set_test_credentials(monkeypatch)
    captured = {}

    class FakeOrder:
        def create(self, *, data):
            captured.update(data)
            return {"id": "order_123", "amount": 1250, "currency": "INR"}

    class FakeGateway:
        order = FakeOrder()

    monkeypatch.setattr(main, "get_gateway", lambda _settings: FakeGateway())
    response = client.post("/api/create-order", json={"amount_rupees": "12.50", "provider": "razorpay"})

    assert response.status_code == 200
    assert captured["amount"] == 1250
    assert captured["currency"] == "INR"
    assert response.json()["order_id"] == "order_123"
    assert response.json()["amount_paise"] == 1250


def test_create_order_rejects_invalid_amounts(monkeypatch):
    set_test_credentials(monkeypatch)

    for amount in ("0", "0.99", "100000.01", "1.001"):
        response = client.post("/api/create-order", json={"amount_rupees": amount, "provider": "razorpay"})
        assert response.status_code == 422


def test_create_phonepe_order_uses_amount_and_returns_redirect(monkeypatch):
    set_phonepe_credentials(monkeypatch)
    captured = {}

    def fake_phonepe_request(_settings, method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs["json"]})
        return {"redirectUrl": "https://mercury-uat.phonepe.com/transact/checkout"}

    monkeypatch.setattr(main, "phonepe_request", fake_phonepe_request)
    response = client.post(
        "/api/create-order",
        json={"amount_rupees": "25.50", "provider": "phonepe"},
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "phonepe"
    assert response.json()["amount_paise"] == 2550
    assert response.json()["redirect_url"].startswith("https://mercury-uat.phonepe.com/")
    assert captured["path"] == "/checkout/v2/pay"
    assert captured["amount"] == 2550
    assert captured["paymentFlow"]["merchantUrls"]["redirectUrl"].endswith(
        f"merchant_order_id={response.json()['merchant_order_id']}"
    )


def test_phonepe_return_page_and_status_endpoint(monkeypatch):
    set_phonepe_credentials(monkeypatch)
    merchant_order_id = "rozpay_0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(
        main,
        "phonepe_payment_summary",
        lambda _settings, order_id: {"state": "COMPLETED", "payment_id": "phonepe_txn_1", "reason": None}
        if order_id == merchant_order_id
        else {},
    )

    return_page = client.get(f"/payment/phonepe/return?merchant_order_id={merchant_order_id}")
    status = client.get(f"/api/phonepe/status/{merchant_order_id}")

    assert return_page.status_code == 200
    assert "Confirming your payment" in return_page.text
    assert status.status_code == 200
    assert status.json()["state"] == "COMPLETED"
    assert status.json()["payment_id"] == "phonepe_txn_1"


def test_phonepe_success_page_requires_completed_order(monkeypatch):
    set_phonepe_credentials(monkeypatch)
    merchant_order_id = "rozpay_0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(
        main,
        "phonepe_payment_summary",
        lambda _settings, _order_id: {"state": "COMPLETED", "payment_id": "phonepe_txn_1", "reason": None},
    )

    response = client.get(
        f"/payment/success?provider=phonepe&merchant_order_id={merchant_order_id}&payment_id=phonepe_txn_1"
    )

    assert response.status_code == 200
    assert "payment was confirmed successfully" in response.text.lower()


def test_verify_payment_accepts_captured_matching_five_rupee_payment(monkeypatch):
    set_test_credentials(monkeypatch)

    class FakeUtility:
        def verify_payment_signature(self, signature):
            assert signature["razorpay_order_id"] == "order_123"

    class FakePayment:
        def fetch(self, payment_id):
            assert payment_id == "pay_123"
            return {"order_id": "order_123", "status": "captured", "amount": 500, "currency": "INR"}

    class FakeOrder:
        def fetch(self, order_id):
            assert order_id == "order_123"
            return {"amount": 500, "currency": "INR"}

    class FakeGateway:
        utility = FakeUtility()
        payment = FakePayment()
        order = FakeOrder()

    monkeypatch.setattr(main, "get_gateway", lambda _settings: FakeGateway())
    response = client.post("/api/verify-payment", json=PAYMENT)

    assert response.status_code == 200
    assert response.json() == {"status": "success", "payment_id": "pay_123"}


def test_verify_payment_rejects_payment_amount_not_matching_order(monkeypatch):
    set_test_credentials(monkeypatch)

    class FakeUtility:
        def verify_payment_signature(self, _signature):
            return None

    class FakePayment:
        def fetch(self, _payment_id):
            return {"order_id": "order_123", "status": "captured", "amount": 500, "currency": "INR"}

    class FakeOrder:
        def fetch(self, _order_id):
            return {"amount": 1000, "currency": "INR"}

    class FakeGateway:
        utility = FakeUtility()
        payment = FakePayment()
        order = FakeOrder()

    monkeypatch.setattr(main, "get_gateway", lambda _settings: FakeGateway())
    response = client.post("/api/verify-payment", json=PAYMENT)

    assert response.status_code == 400


def test_verify_payment_rejects_invalid_signature(monkeypatch):
    set_test_credentials(monkeypatch)

    class FakeUtility:
        def verify_payment_signature(self, _signature):
            raise main.SignatureVerificationError("bad signature")

    class FakeGateway:
        utility = FakeUtility()

    monkeypatch.setattr(main, "get_gateway", lambda _settings: FakeGateway())
    response = client.post("/api/verify-payment", json=PAYMENT)

    assert response.status_code == 400
