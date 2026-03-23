(function () {
  let initialized = false;
  let state = {
    accounts: [],
    taskMountSelector: null,
    taskRefreshUrl: null,
  };
  let dialog;
  let payForm;
  let payAccountField;
  let payAmountField;
  let payOrderIdField;
  let payUrlField;
  let payTitle;
  let dialogSubmitButton;
  let toastHost;
  let pollingHandle = null;

  function getCookie(name) {
    const cookies = document.cookie ? document.cookie.split(";") : [];
    for (const cookie of cookies) {
      const trimmed = cookie.trim();
      if (trimmed.startsWith(`${name}=`)) {
        return decodeURIComponent(trimmed.slice(name.length + 1));
      }
    }
    return "";
  }

  function showToast(message, kind) {
    ensureToastHost();
    const notice = document.createElement("div");
    notice.className = `pos-toast ${kind || "info"}`;
    notice.textContent = message;
    toastHost.appendChild(notice);

    window.setTimeout(() => {
      notice.classList.add("is-leaving");
      window.setTimeout(() => notice.remove(), 220);
    }, 2600);
  }

  function ensureToastHost() {
    if (toastHost) {
      return;
    }
    toastHost = document.createElement("div");
    toastHost.className = "pos-toast-host";
    document.body.appendChild(toastHost);
  }

  function setBusyState(element, isBusy, busyLabel) {
    if (!element) {
      return;
    }

    if (isBusy) {
      if (!element.dataset.originalLabel) {
        element.dataset.originalLabel = element.textContent;
      }
      element.disabled = true;
      element.setAttribute("aria-busy", "true");
      if (busyLabel) {
        element.textContent = busyLabel;
      }
      return;
    }

    element.disabled = false;
    element.removeAttribute("aria-busy");
    if (element.dataset.originalLabel) {
      element.textContent = element.dataset.originalLabel;
      delete element.dataset.originalLabel;
    }
  }

  function ensureDialog() {
    if (dialog) {
      return;
    }

    dialog = document.createElement("dialog");
    dialog.className = "pos-dialog";
    dialog.innerHTML = `
      <div class="pos-dialog-inner">
        <div class="pos-dialog-head">
          <div>
            <div class="pos-dialog-title">Tez to'lov</div>
            <div class="muted small" id="posQuickPayTitle">Buyurtma uchun to'lovni tasdiqlang.</div>
          </div>
          <button class="btn btn-ghost" type="button" data-close-quick-pay>Yopish</button>
        </div>
        <form id="posQuickPayForm" class="pos-pay-form">
          <input type="hidden" name="order_id" id="posQuickPayOrderId">
          <input type="hidden" name="url" id="posQuickPayUrl">
          <div class="pos-field" id="posQuickPayAccountField"></div>
          <div class="pos-field">
            <label>Summa</label>
            <input class="control" type="number" min="1" step="1" id="posQuickPayAmount" name="amount" required>
          </div>
          <button class="btn btn-primary" type="submit">To'lovni yakunlash</button>
        </form>
      </div>
    `;

    document.body.appendChild(dialog);

    payForm = dialog.querySelector("#posQuickPayForm");
    payAccountField = dialog.querySelector("#posQuickPayAccountField");
    payAmountField = dialog.querySelector("#posQuickPayAmount");
    payOrderIdField = dialog.querySelector("#posQuickPayOrderId");
    payUrlField = dialog.querySelector("#posQuickPayUrl");
    payTitle = dialog.querySelector("#posQuickPayTitle");
    dialogSubmitButton = payForm.querySelector("[type='submit']");

    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) {
        dialog.close();
      }
    });

    dialog.querySelector("[data-close-quick-pay]").addEventListener("click", () => {
      dialog.close();
    });

    payForm.addEventListener("submit", async (event) => {
      event.preventDefault();

      const formData = new FormData();
      const accountField = payAccountField.querySelector("select, input[type='hidden']");
      if (accountField && accountField.value) {
        formData.append("account_id", accountField.value);
      }
      formData.append("amount", payAmountField.value);

      const ok = await submitAction({
        url: payUrlField.value,
        action: "pay",
        orderId: payOrderIdField.value,
        orderShort: payForm.dataset.orderShort || "",
        formData,
        trigger: dialogSubmitButton,
      });

      if (ok && dialog.open) {
        dialog.close();
      }
    });
  }

  function buildAccountField() {
    const accounts = state.accounts || [];
    if (!accounts.length) {
      return `
        <label>To'lov hisobi</label>
        <div class="notice notice-warning">Faol kassa topilmadi. Avval filial uchun hisob yarating.</div>
      `;
    }

    if (accounts.length === 1) {
      return `
        <label>To'lov hisobi</label>
        <input type="hidden" value="${accounts[0].id}">
        <div class="control control-static">${accounts[0].name}</div>
      `;
    }

    const options = accounts
      .map((account) => `<option value="${account.id}">${account.name}</option>`)
      .join("");

    return `
      <label>Kassa</label>
      <select class="control" required>
        <option value="">Tanlang...</option>
        ${options}
      </select>
    `;
  }

  function openPayDialog(button) {
    ensureDialog();

    const orderShort = button.dataset.orderShort || button.dataset.orderId || "";
    const due = Number(button.dataset.orderDue || 0);

    payTitle.textContent = `#${orderShort} buyurtma uchun to'lovni tasdiqlang.`;
    payOrderIdField.value = button.dataset.orderId || "";
    payUrlField.value = button.dataset.url || "";
    payForm.dataset.orderShort = orderShort;
    payAmountField.value = due > 0 ? String(due) : "";
    payAccountField.innerHTML = buildAccountField();

    dialog.showModal();
  }

  function refreshTaskMount(payload) {
    if (!state.taskMountSelector || !state.taskRefreshUrl) {
      return Promise.resolve();
    }

    const mount = document.querySelector(state.taskMountSelector);
    if (!mount) {
      return Promise.resolve();
    }

    if (payload && payload.pending_tasks_html) {
      mount.innerHTML = payload.pending_tasks_html;
      return Promise.resolve();
    }

    return fetch(state.taskRefreshUrl, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then((response) => response.json())
      .then((payload) => {
        if (payload.ok) {
          mount.innerHTML = payload.html;
        }
      })
      .catch((error) => {
        console.error(error);
      });
  }

  function updateOrderStatus(orderId, statusHtml) {
    if (!orderId || !statusHtml) {
      return;
    }

    const current = document.getElementById(`order-status-${orderId}`);
    if (current) {
      current.outerHTML = statusHtml;
    }
  }

  async function submitAction({ url, action, orderId, orderShort, formData, trigger }) {
    const busyLabel = action === "pay" ? "Saqlanmoqda..." : "Yangilanmoqda...";
    setBusyState(trigger, true, busyLabel);

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: formData,
      });

      let payload = {};
      try {
        payload = await response.json();
      } catch (error) {
        payload = { ok: false, message: "Javobni o'qib bo'lmadi." };
      }

      if (!response.ok || !payload.ok) {
        showToast(payload.message || "Amal bajarilmadi.", "error");
        return false;
      }

      updateOrderStatus(orderId, payload.status_html);
      await refreshTaskMount(payload);

      const successMessage = payload.message || `#${orderShort || orderId} buyurtma yangilandi.`;
      showToast(successMessage, action === "pay" ? "success" : "info");
      return true;
    } catch (error) {
      console.error(error);
      showToast("Tarmoq xatosi sabab amal bajarilmadi.", "error");
      return false;
    } finally {
      setBusyState(trigger, false);
    }
  }

  function handleActionButton(button) {
    const action = button.dataset.orderAction;
    if (!action || !button.dataset.url) {
      return;
    }

    if (action === "pay") {
      if (!state.accounts.length) {
        showToast("Faol kassa topilmadi. Admin: filial uchun hisob yarating.", "error");
        return;
      }

      if (state.accounts.length > 1) {
        openPayDialog(button);
        return;
      }

      const formData = new FormData();
      formData.append("account_id", state.accounts[0].id);
      formData.append("amount", button.dataset.orderDue || "");

      submitAction({
        url: button.dataset.url,
        action,
        orderId: button.dataset.orderId || "",
        orderShort: button.dataset.orderShort || "",
        formData,
        trigger: button,
      });
      return;
    }

    const formData = new FormData();
    submitAction({
      url: button.dataset.url,
      action,
      orderId: button.dataset.orderId || "",
      orderShort: button.dataset.orderShort || "",
      formData,
      trigger: button,
    });
  }

  window.initPosQuickActions = function initPosQuickActions(options) {
    state = {
      ...state,
      ...(options || {}),
    };

    ensureToastHost();

    if (!initialized) {
      initialized = true;
      document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-order-action]");
        if (!button) {
          return;
        }
        handleActionButton(button);
      });
    }

    if (pollingHandle) {
      window.clearInterval(pollingHandle);
      pollingHandle = null;
    }

    if (state.taskMountSelector && state.taskRefreshUrl) {
      pollingHandle = window.setInterval(() => {
        refreshTaskMount();
      }, 15000);
    }
  };
})();
