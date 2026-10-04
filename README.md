# RozPay — FastAPI + Razorpay / PhonePe Checkout demo

A small payment app with a responsive HTML checkout page. Customers enter the INR amount and choose Razorpay or PhonePe. The server validates the amount, creates the order with the selected provider, then verifies the payment with that provider before showing success.

## Requirements

- Python 3.10+
- Razorpay and/or PhonePe merchant account credentials

## Setup

1. Create test credentials for the gateway(s) you want to offer. For Razorpay, create test API keys in its Dashboard. For PhonePe, obtain the Standard Checkout API credentials from your PhonePe merchant account. Keep all secrets private.
2. Create a virtual environment and install dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Configure `.env` with the credentials for the gateways you want to offer. Leave a provider's variables blank to hide that option. Use `PHONEPE_ENVIRONMENT=sandbox` with PhonePe sandbox credentials, then set it to `production` only with production credentials. The checkout starts with ₹5.00 selected; the payer can enter ₹1.00–₹100,000.00 with up to two decimal places. The server validates the amount and creates the order; editing the browser request cannot bypass those checks. The `.env.example` file is only a template and contains no real credentials.
4. Start the application:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn main:app --reload
   ```

5. Open `http://127.0.0.1:8000` in a browser, enter an amount, choose a configured gateway, and continue to its hosted checkout. Use the provider's test/sandbox payment details; do not use real credentials or real payments while testing.

## Tests

Run the unit tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Payment flow and deployment notes

- `GET /api/config` exposes which gateways are configured and only the public Razorpay key ID. PhonePe OAuth credentials and Razorpay secret stay server-side.
- `POST /api/create-order` creates a provider-specific order server-side. Razorpay uses its hosted Checkout modal; PhonePe uses its Standard Checkout redirect.
- `POST /api/verify-payment` validates the Razorpay signature and verifies its captured payment against the order.
- PhonePe returns to `/payment/phonepe/return`; the return page polls the authenticated PhonePe order-status API and does not trust the browser redirect alone.
- Confirmed payments redirect to `/payment/success` and display the provider payment ID. The server rechecks captured/completed status before serving that page. Declined/unconfirmed payments redirect to `/payment/failure` and display an available provider reason.
- Enable automatic capture in your Razorpay Dashboard for this demo; otherwise a payment can remain authorized and the app will not report it as captured.
- For production, use HTTPS, secure and rotate secrets, persist orders/payment state in a database, add idempotency and reconciliation, and implement a signed Razorpay webhook for reliable asynchronous updates. Do not rely solely on a browser callback for fulfillment. The webhook endpoint is intentionally not included here.
- This demo does not include customer accounts, a database, refunds, or order fulfillment.
