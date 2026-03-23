document.addEventListener("DOMContentLoaded", () => {
  initThemeToggle();
  initMobileMenu();
  initSmoothScroll();
  initLiveMenu();
});

function initThemeToggle() {
  const themeToggle = document.getElementById("theme-toggle");
  const prefersDarkScheme = window.matchMedia("(prefers-color-scheme: dark)");

  const currentTheme = localStorage.getItem("theme");
  if (currentTheme) {
    document.documentElement.setAttribute("data-theme", currentTheme);
  } else if (prefersDarkScheme.matches) {
    document.documentElement.setAttribute("data-theme", "dark");
  }

  if (!themeToggle) {
    return;
  }

  themeToggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    const nextTheme = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", nextTheme);
    localStorage.setItem("theme", nextTheme);
  });
}

function initMobileMenu() {
  const hamburger = document.querySelector(".hamburger");
  const navLinks = document.querySelector(".nav-links");

  if (!hamburger || !navLinks) {
    return;
  }

  const openLabel = hamburger.dataset.openLabel || "Menu";
  const closeLabel = hamburger.dataset.closeLabel || "Yopish";

  const syncButtonLabel = () => {
    const isOpen = navLinks.classList.contains("active");
    hamburger.textContent = isOpen ? closeLabel : openLabel;
    hamburger.setAttribute("aria-expanded", isOpen ? "true" : "false");
  };

  hamburger.addEventListener("click", () => {
    navLinks.classList.toggle("active");
    syncButtonLabel();
  });

  syncButtonLabel();
}

function initSmoothScroll() {
  const navLinks = document.querySelector(".nav-links");
  const hamburger = document.querySelector(".hamburger");

  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener("click", function onAnchorClick(event) {
      const selector = this.getAttribute("href");
      const target = selector ? document.querySelector(selector) : null;
      if (!target) {
        return;
      }

      event.preventDefault();
      target.scrollIntoView({ behavior: "smooth" });

      if (navLinks && navLinks.classList.contains("active")) {
        navLinks.classList.remove("active");
        if (hamburger) {
          hamburger.textContent = hamburger.dataset.openLabel || "Menu";
          hamburger.setAttribute("aria-expanded", "false");
        }
      }
    });
  });
}

function initLiveMenu() {
  const form = document.getElementById("landingMenuFilters");
  if (!form) {
    return;
  }

  const liveUrl = form.dataset.liveUrl;
  const searchInput = document.getElementById("landingMenuSearch");
  const clearButton = document.getElementById("landingMenuSearchClear");
  const typeInput = document.getElementById("landingMenuTypeInput");
  const categoryInput = document.getElementById("landingMenuCategoryInput");
  const typeFilters = document.getElementById("landingTypeFilters");
  const panel = document.getElementById("landingMenuPanel");
  const liveStatus = document.getElementById("landingMenuLiveStatus");
  let activeController = null;

  const syncClearButton = () => {
    if (!clearButton || !searchInput) {
      return;
    }
    clearButton.hidden = !searchInput.value.trim();
  };

  const syncTypeButtons = () => {
    if (!typeFilters || !typeInput) {
      return;
    }

    typeFilters.querySelectorAll("[data-type]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.type === typeInput.value);
    });
  };

  const syncCategoryButtons = () => {
    panel.querySelectorAll("[data-category]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.category === categoryInput.value);
    });
  };

  const buildQueryString = () => {
    const params = new URLSearchParams();
    const query = searchInput ? searchInput.value.trim() : "";

    if (query) {
      params.set("q", query);
    }
    if (typeInput && typeInput.value) {
      params.set("type", typeInput.value);
    }
    if (categoryInput && categoryInput.value) {
      params.set("category", categoryInput.value);
    }

    return params;
  };

  const setStatus = (message, isLoading = false) => {
    if (!liveStatus) {
      return;
    }
    liveStatus.textContent = message;
    liveStatus.classList.toggle("is-loading", isLoading);
  };

  const updateBrowserUrl = () => {
    const params = buildQueryString();
    const queryString = params.toString();
    const nextUrl = queryString ? `${form.action}?${queryString}` : form.action;
    window.history.replaceState({}, "", nextUrl);
  };

  const fetchMenu = async () => {
    const params = buildQueryString();
    const requestUrl = `${liveUrl}?${params.toString()}`;

    if (activeController) {
      activeController.abort();
    }
    activeController = new AbortController();

    panel.classList.add("is-loading");
    setStatus("Natijalar yangilanmoqda...", true);

    try {
      const response = await fetch(requestUrl, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal: activeController.signal,
      });
      if (!response.ok) {
        throw new Error(`Menu request failed: ${response.status}`);
      }

      const payload = await response.json();
      panel.innerHTML = payload.html;

      if (typeInput) {
        typeInput.value = payload.type || "";
      }
      if (categoryInput) {
        categoryInput.value = payload.category || "";
      }

      syncTypeButtons();
      syncCategoryButtons();
      syncClearButton();
      updateBrowserUrl();
      setStatus(`${payload.count} ta natija ko'rsatildi`);
    } catch (error) {
      if (error.name === "AbortError") {
        return;
      }
      console.error(error);
      setStatus("Natijalarni yangilashda xatolik yuz berdi");
    } finally {
      panel.classList.remove("is-loading");
      liveStatus && liveStatus.classList.remove("is-loading");
    }
  };

  const debounce = (callback, delay) => {
    let timerId = null;
    return (...args) => {
      window.clearTimeout(timerId);
      timerId = window.setTimeout(() => callback(...args), delay);
    };
  };

  const debouncedFetch = debounce(fetchMenu, 180);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    fetchMenu();
  });

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      syncClearButton();
      debouncedFetch();
    });
  }

  if (clearButton && searchInput) {
    clearButton.addEventListener("click", () => {
      searchInput.value = "";
      syncClearButton();
      fetchMenu();
      searchInput.focus();
    });
  }

  if (typeFilters) {
    typeFilters.addEventListener("click", (event) => {
      const button = event.target.closest("[data-type]");
      if (!button) {
        return;
      }

      typeInput.value = button.dataset.type || "";
      categoryInput.value = "";
      syncTypeButtons();
      fetchMenu();
    });
  }

  panel.addEventListener("click", (event) => {
    const categoryButton = event.target.closest("[data-category]");
    if (!categoryButton) {
      return;
    }

    categoryInput.value = categoryButton.dataset.category || "";
    syncCategoryButtons();
    fetchMenu();
  });

  syncTypeButtons();
  syncCategoryButtons();
  syncClearButton();
  const initialCount = panel.querySelector(".menu-results-meta")?.textContent || "0 ta natija";
  setStatus(`${initialCount} ko'rsatildi`);
}
