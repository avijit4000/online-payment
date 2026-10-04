# RozPay — FastAPI + Razorpay Checkout demo

A small payment app with a responsive HTML checkout page. Customers enter the INR amount, the server validates it and creates the Razorpay order in paise, then verifies the checkout signature and confirms the captured payment matches the corresponding Razorpay order before returning success.

## Requirements

- Python 3.10+
- Razorpay account and API test keys

## Setup

1. Create test API keys in the Razorpay Dashboard under **Account & Settings → API Keys**. Keep the key secret private.
2. Create a virtual environment and install dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Configure `.env` with your Razorpay **test** key ID and key secret. If you already have a `.env`, keep your credentials unchanged. The checkout starts with ₹5.00 selected; the payer can enter any amount from ₹1.00 to ₹100,000.00, with up to two decimal places. The server validates the amount and creates the order; editing the browser request cannot bypass those checks. The `.env.example` file is only a template and contains no real credentials.
4. Start the application:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn main:app --reload
   ```

5. Open `http://127.0.0.1:8000` in a browser. Use Razorpay test mode payment details from their Dashboard/official testing guide; do not use real credentials or real payments while testing.

## Tests

Run the unit tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Payment flow and deployment notes

- `GET /api/config` returns public checkout details and the Razorpay **key ID** only.
- `POST /api/create-order` creates each order server-side. The browser cannot choose the amount.
- `POST /api/verify-payment` validates the Razorpay signature and confirms the payment is captured and belongs to the verified order. The UI shows success only after this endpoint succeeds.
- A verified payment redirects to `/payment/success?payment_id=...`; the server checks the payment is captured before returning the success page, which displays the payment ID. A declined or unconfirmed payment redirects to `/payment/failure` and shows the reason reported by Razorpay or the verification API.
- Enable automatic capture in your Razorpay Dashboard for this demo; otherwise a payment can remain authorized and the app will not report it as captured.
- For production, use HTTPS, secure and rotate secrets, persist orders/payment state in a database, add idempotency and reconciliation, and implement a signed Razorpay webhook for reliable asynchronous updates. Do not rely solely on a browser callback for fulfillment. The webhook endpoint is intentionally not included here.
- This demo does not include customer accounts, a database, refunds, or order fulfillment.
