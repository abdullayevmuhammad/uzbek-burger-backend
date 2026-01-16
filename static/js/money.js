(function () {
  function onlyDigits(str) {
    return (str || "").replace(/[^\d]/g, "");
  }

  function group3(str) {
    // "1250000" -> "1 250 000"
    if (!str) return "";
    return str.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }

  function formatInput(el) {
    const digits = onlyDigits(el.value);
    el.value = group3(digits);
  }

  function attach(el) {
    if (!el) return;

    // input paytida formatlash
    el.addEventListener("input", () => formatInput(el));

    // form submit bo‘layotganda: serverga faqat raqam yuborish
    const form = el.closest("form");
    if (form && !form.dataset.moneyBound) {
      form.dataset.moneyBound = "1";
      form.addEventListener("submit", () => {
        form.querySelectorAll("[data-money]").forEach((x) => {
          x.value = onlyDigits(x.value) || "0";
        });
      });
    }

    // load paytida ham formatlab qo‘yamiz (edit case)
    formatInput(el);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-money]").forEach(attach);
  });
})();
