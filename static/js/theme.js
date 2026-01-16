(function () {
  const KEY = "ub_theme"; // 'dark' | 'light' | 'system'
  const root = document.documentElement;

  function applyTheme(v) {
    const theme = v || "system";
    root.setAttribute("data-theme", theme);

    // agar tema select bo'lsa - sync
    const sel = document.getElementById("themeSelect");
    if (sel && sel.value !== theme) sel.value = theme;
  }

  // load saved theme
  const saved = localStorage.getItem(KEY) || "system";
  applyTheme(saved);

  // expose
  window.setTheme = function (theme) {
    localStorage.setItem(KEY, theme);
    applyTheme(theme);
  };

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(localStorage.getItem(KEY) || "system");
  });
})();
