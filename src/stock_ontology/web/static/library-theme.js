(() => {
  const storageKey = "stock-ontology-library-theme";
  const root = document.documentElement;

  function savedTheme() {
    try {
      return localStorage.getItem(storageKey) === "classic" ? "classic" : "modern";
    } catch {
      return root.dataset.theme || "modern";
    }
  }

  // Set the preference before CSS loads so Classic visits do not flash Modern.
  root.dataset.theme = savedTheme();

  document.addEventListener("DOMContentLoaded", () => {
    const control = document.getElementById("library-theme");
    function reflectPreference() {
      root.dataset.theme = savedTheme();
      control.value = root.dataset.theme;
    }

    reflectPreference();
    control.addEventListener("change", () => {
      root.dataset.theme = control.value;
      try {
        localStorage.setItem(storageKey, control.value);
      } catch {
        // Theme switching still works on this page if browser storage is disabled.
      }
    });
    window.addEventListener("pageshow", reflectPreference);
    window.addEventListener("storage", event => {
      if (event.key === storageKey || event.key === null) reflectPreference();
    });
  });
})();
