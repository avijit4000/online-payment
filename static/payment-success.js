const paymentId = new URLSearchParams(window.location.search).get("payment_id");
document.querySelector("#year").textContent = new Date().getFullYear();
document.querySelector("#payment-id").textContent = paymentId || "Not available";
