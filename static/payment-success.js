const paymentId = new URLSearchParams(window.location.search).get("payment_id");
const provider = new URLSearchParams(window.location.search).get("provider");
document.querySelector("#year").textContent = new Date().getFullYear();
document.querySelector("#payment-id").textContent = paymentId || "Not available";
document.querySelector("#gateway-name").textContent = provider === "phonepe" ? "PhonePe" : "Razorpay";
