// OSS Radar — JS tăng cường dần (QĐ-20). Trang dùng đủ khi tắt JS; file này chỉ làm thao tác nhanh hơn.
// DEBT(D-010): chưa có test tự động (dự án không có trình chạy JS) — kiểm bằng trình duyệt mỗi PR.
(function () {
  "use strict";

  document.documentElement.classList.add("js");

  var AUTO_FIELDS = "select, input[type=checkbox], input[type=radio], input[type=number]";

  // Form lọc tự gửi khi đổi ô chọn, ô tick, ô số. Ô chữ vẫn chờ Enter để không gửi theo từng phím.
  document.addEventListener("change", function (event) {
    var field = event.target;
    if (!(field instanceof Element) || !field.matches(AUTO_FIELDS)) return;
    var form = field.closest("form[data-autosubmit]");
    if (!form) return;
    if (typeof form.requestSubmit === "function") {
      form.requestSubmit();
    } else {
      form.submit();
    }
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.hasAttribute("data-confirm") && !window.confirm(form.getAttribute("data-confirm"))) {
      event.preventDefault();
      return;
    }
    // Bỏ ô rỗng khỏi đường dẫn cho gọn; máy chủ không dựa vào việc này.
    if (form.hasAttribute("data-clean-query")) {
      Array.prototype.forEach.call(form.elements, function (field) {
        var empty = field.name && "value" in field && field.value === "" && field.type !== "submit";
        if (empty) field.disabled = true;
      });
      // Trang được giữ trong bộ nhớ đệm khi bấm Quay lại: bật lại các ô để form không bị khoá.
      window.setTimeout(function () {
        Array.prototype.forEach.call(form.elements, function (field) {
          field.disabled = false;
        });
      }, 0);
    }
  });

  // Phím "/" đưa con trỏ vào ô tìm kiếm, trừ khi đang gõ ở ô khác.
  document.addEventListener("keydown", function (event) {
    if (event.key !== "/" || event.ctrlKey || event.altKey || event.metaKey) return;
    var active = document.activeElement;
    var typing =
      active &&
      (active.matches("input, textarea, select") || active.isContentEditable);
    if (typing) return;
    var search = document.querySelector("[data-search]");
    if (!search) return;
    event.preventDefault();
    search.focus();
    if (typeof search.select === "function") search.select();
  });
})();
