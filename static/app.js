const payButton = document.querySelector("#pay-button");
const buttonLabel = document.querySelector("#button-label");
const statusBox = document.querySelector("#payment-status");
const amountInput = document.querySelector("#amount-input");
const formatter = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });
let checkoutConfig;
let pendingPayment;

document.querySelector("#year").textContent = new Date().getFullYear();

function showStatus(message, kind = "") {
  statusBox.textContent = message;
  statusBox.className = `status ${kind}`.trim();
  statusBox.hidden = false;
}

function setBusy(busy, label) {
  payButton.disabled = busy;
  buttonLabel.textContent = label;
}

function selectedProvider() {
  return document.querySelector('input[name="gateway"]:checked')?.value || "";
}

function updateAmountDisplay() {
  if (!amountInput.validity.valid || !amountInput.value) {
    payButton.disabled = true;
    return;
  }
  const price = formatter.format(Number(amountInput.value));
  document.querySelector("#product-price").textContent = price;
  document.querySelector("#subtotal").textContent = price;
  document.querySelector("#total").textContent = price;
  payButton.disabled = !checkoutConfig?.providers?.[selectedProvider()];
}

async function readJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((issue) => issue.msg).join("; ")
      : data.detail;
    throw new Error(detail || "Something went wrong. Please try again.");
  }
  return data;
}

function goToPaymentFailure(reason, paymentId = "") {
  const query = new URLSearchParams({ reason: reason || "Payment could not be completed." });
  if (paymentId) query.set("payment_id", paymentId);
  window.location.assign(`/payment/failure?${query.toString()}`);
}

async function verifyPayment(response) {
  setBusy(true, "Verifying payment…");
  showStatus("Payment received. Verifying securely with the server…", "pending");
  try {
    const result = await readJson(await fetch("/api/verify-payment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(response),
    }));
    if (result.status !== "success") throw new Error("The payment has not been confirmed yet.");
    pendingPayment = undefined;
    window.location.assign(`/payment/success?payment_id=${encodeURIComponent(result.payment_id)}`);
  } catch (error) {
    goToPaymentFailure(`We could not confirm this payment: ${error.message}`, response.razorpay_payment_id);
  }
}

async function initialize() {
  try {
    checkoutConfig = await readJson(await fetch("/api/config"));
    document.querySelector("#product-name").textContent = checkoutConfig.product_name;
    document.querySelector("#product-description").textContent = checkoutConfig.product_description;
    const razorpayRadio = document.querySelector("#gateway-razorpay");
    const phonepeRadio = document.querySelector("#gateway-phonepe");
    razorpayRadio.disabled = !checkoutConfig.providers.razorpay;
    phonepeRadio.disabled = !checkoutConfig.providers.phonepe;
    if (!checkoutConfig.providers.razorpay && checkoutConfig.providers.phonepe) {
      phonepeRadio.checked = true;
    }
    if (!checkoutConfig.providers.razorpay && !checkoutConfig.providers.phonepe) {
      showStatus("No payment gateway is configured. Add Razorpay or PhonePe credentials to the server .env file.", "error");
    }
    updateAmountDisplay();
    buttonLabel.textContent = checkoutConfig.providers.razorpay || checkoutConfig.providers.phonepe
      ? "Continue to payment"
      : "Checkout unavailable";
  } catch (error) {
    showStatus(error.message, "error");
    setBusy(true, "Checkout unavailable");
  }
}

amountInput.addEventListener("input", updateAmountDisplay);
document.querySelectorAll('input[name="gateway"]').forEach((radio) => {
  radio.addEventListener("change", updateAmountDisplay);
});

payButton.addEventListener("click", async () => {
  if (pendingPayment) {
    await verifyPayment(pendingPayment);
    return;
  }
  if (!checkoutConfig || !window.Razorpay) {
    if (!checkoutConfig || selectedProvider() !== "phonepe") {
      showStatus("Secure checkout could not load. Check your connection and refresh the page.", "error");
      return;
    }
  }
  const provider = selectedProvider();
  if (!checkoutConfig?.providers?.[provider]) {
    showStatus("The selected payment gateway is not configured.", "error");
    return;
  }

  setBusy(true, "Creating secure order…");
  statusBox.hidden = true;
  try {
    const order = await readJson(await fetch("/api/create-order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount_rupees: amountInput.value, provider }),
    }));
    const confirmedAmount = formatter.format(order.amount_paise / 100);
    document.querySelector("#product-price").textContent = confirmedAmount;
    document.querySelector("#subtotal").textContent = confirmedAmount;
    document.querySelector("#total").textContent = confirmedAmount;
    if (order.provider === "phonepe") {
      const checkoutUrl = new URL(order.redirect_url);
      if (checkoutUrl.protocol !== "https:" || !(checkoutUrl.hostname === "phonepe.com" || checkoutUrl.hostname.endsWith(".phonepe.com"))) {
        throw new Error("PhonePe returned an invalid checkout URL.");
      }
      window.location.assign(checkoutUrl.toString());
      return;
    }

    const checkout = new window.Razorpay({
      key: order.key_id,
      amount: order.amount_paise,
      currency: order.currency,
      name: "RozPay",
      description: order.product_name,
      order_id: order.order_id,
      theme: { color: "#16795b" },
      handler: verifyPayment,
      modal: {
        ondismiss: () => {
          setBusy(false, "Continue to payment");
          showStatus("Checkout was closed. No success has been recorded.");
        },
      },
    });
    checkout.on("payment.failed", (event) => {
      const failure = event.error || {};
      const reason = failure.description || failure.reason || failure.code || "Payment was declined. Please try another payment method.";
      const paymentId = failure.metadata?.payment_id || "";
      goToPaymentFailure(reason, paymentId);
    });
    checkout.open();
    setBusy(false, "Continue to payment");
  } catch (error) {
    showStatus(error.message, "error");
    setBusy(false, "Try payment again");
  }
});

initialize();
