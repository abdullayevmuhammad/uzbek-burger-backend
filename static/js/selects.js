document.addEventListener("DOMContentLoaded", () => {
  if (!window.Choices) return;

  document.querySelectorAll("select[data-choices]").forEach((el) => {
    if (el.dataset.choicesInited) return;
    el.dataset.choicesInited = "1";

    const noSearch = el.hasAttribute("data-choices-nosearch");

    new Choices(el, {
      searchEnabled: !noSearch,
      shouldSort: false,
      itemSelectText: "",
      searchPlaceholderValue: "Qidirish...",
      placeholder: true,
      placeholderValue: el.getAttribute("data-placeholder") || "Tanlang...",
      noResultsText: "Topilmadi",
      noChoicesText: "Variant yo‘q",
    });
  });
});
