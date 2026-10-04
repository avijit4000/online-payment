const params = new URLSearchParams(window.location.search);
const merchantOrderId = params.get("merchant_order_id");
const reference = document.querySelector("#order-reference");
const title = document.querySelector("#result-title");
const copy = document.querySelector("#status-copy");
const icon = document.querySelector("#status-icon");
const label = document.querySelector("#status-label");
const backLink = document.querySelector("#back-link");
document.querySelector("#year").textContent = new Date().getFullYear();
reference.textContent = merchantOrderId || "Not available";

function showFailure(reason) {
  const query = new URLSearchParams({ reason: reason || "PhonePe reported that the payment did not complete." });
  query.set("provider", "phonepe");
  if (merchantOrderId) query.set("merchant_order_id", merchantOrderId);
  window.location.replace(`/payment/failure?${query.toString()}`);
}

async function checkStatus() {
  if (!merchantOrderId || !/^rozpay_[a-f0-9]{32}$/.test(merchantOrderId)) {
    showFailure("The PhonePe order reference is missing or invalid.");
    return;
  }

  try {
    const response = await fetch(`/api/phonepe/status/${encodeURIComponent(merchantOrderId)}`);
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "PhonePe payment status could not be checked.");

    if (result.state === "COMPLETED") {
      if (!result.payment_id) throw new Error("PhonePe completed the order but returned no payment ID.");
      const query = new URLSearchParams({
        provider: "phonepe",
        merchant_order_id: merchantOrderId,
        payment_id: result.payment_id,
      });
      window.location.replace(`/payment/success?${query.toString()}`);
      return;
    }

    if (result.state === "FAILED" || result.state === "CANCELLED") {
      showFailure(result.reason || `PhonePe payment state: ${result.state}.`);
      return;
    }
  } catch (error) {
    title.textContent = "Still checking your payment";
    copy.textContent = `${error.message} We will retry automatically. Please keep this page open.`;
  }

  window.setTimeout(checkStatus, 2500);
}

checkStatus();
