// taxonomy/static/taxonomy/js/tree/tree_init.js
// Server-side variables and dropdown initialization for tree page

(function() {
  "use strict";

  // Initialize dropdown manually with vanilla JS (Tabler doesn't expose bootstrap global)
  document.addEventListener("DOMContentLoaded", function() {
    const vizRankBtn = document.getElementById("vizRankBtn");
    const dropdownMenu = vizRankBtn ? vizRankBtn.nextElementSibling : null;
    
    if (vizRankBtn && dropdownMenu) {
      // Toggle dropdown on button click
      vizRankBtn.addEventListener("click", function(e) {
        e.stopPropagation();
        const isOpen = dropdownMenu.classList.contains("show");
        // Close all other dropdowns first
        document.querySelectorAll(".dropdown-menu.show").forEach(m => m.classList.remove("show"));
        if (!isOpen) {
          dropdownMenu.classList.add("show");
        }
      });
      
      // Close dropdown when clicking outside
      document.addEventListener("click", function(e) {
        if (!vizRankBtn.contains(e.target) && !dropdownMenu.contains(e.target)) {
          dropdownMenu.classList.remove("show");
        }
      });
      
      // Close dropdown when selecting an item
      dropdownMenu.querySelectorAll(".dropdown-item").forEach(function(item) {
        item.addEventListener("click", function() {
          dropdownMenu.classList.remove("show");
        });
      });
    }
  });
})();
