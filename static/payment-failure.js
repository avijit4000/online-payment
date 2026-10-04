const query = new URLSearchParams(window.location.search);
const reason = query.get("reason");
const paymentId = query.get("payment_id");
const provider = query.get("provider");
document.querySelector("#year").textContent = new Date().getFullYear();
document.querySelector("#gateway-name").textContent = provider === "phonepe" ? "PhonePe" : "Razorpay";
document.querySelector("#failure-reason").textContent = reason || "The payment was declined or cancelled. Please try another payment method.";
if (paymentId) {
  document.querySelector("#payment-id").textContent = paymentId;
  document.querySelector("#payment-id-box").hidden = false;
}
