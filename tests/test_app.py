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


def test_payment_page_is_served():
    response = client.get("/")

    assert response.status_code == 200
    assert "Order summary" in response.text


def test_success_page_requires_captured_payment(monkeypatch):
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


def test_config_requires_credentials(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    response = client.get("/api/config")

    assert response.status_code == 503


def test_config_returns_public_settings_but_not_secret(monkeypatch):
    set_test_credentials(monkeypatch)
    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["key_id"] == "rzp_test_public"
    assert "amount_paise" not in response.json()
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
    response = client.post("/api/create-order", json={"amount_rupees": "12.50"})

    assert response.status_code == 200
    assert captured["amount"] == 1250
    assert captured["currency"] == "INR"
    assert response.json()["order_id"] == "order_123"
    assert response.json()["amount_paise"] == 1250


def test_create_order_rejects_invalid_amounts(monkeypatch):
    set_test_credentials(monkeypatch)

    for amount in ("0", "0.99", "100000.01", "1.001"):
        response = client.post("/api/create-order", json={"amount_rupees": amount})
        assert response.status_code == 422


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
