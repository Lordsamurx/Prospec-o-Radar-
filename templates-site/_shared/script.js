/* Amostras: aparecer ao rolar, pedido e agendamento pelo WhatsApp. Sem rastreamento, sem cookies. */
(function () {
  var items = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    var io = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); } }); }, { threshold: .12 });
    items.forEach(function (el) { io.observe(el); });
  } else { items.forEach(function (el) { el.classList.add("is-in"); }); }

  function send(root, text) {
    var wa = root.getAttribute("data-wa"), tel = root.getAttribute("data-tel");
    if (wa) window.open("https://wa.me/" + wa + "?text=" + encodeURIComponent(text), "_blank", "noopener");
    else if (tel) location.href = "tel:" + tel;
  }

  /* cardápio: soma itens e monta o pedido */
  var menu = document.querySelector("[data-menu]");
  if (menu) {
    var out = menu.querySelector("[data-order-count]"), btn = menu.querySelector("[data-order-send]");
    var update = function () {
      var n = 0;
      menu.querySelectorAll("[data-qty]").forEach(function (q) { n += Number(q.textContent); });
      out.textContent = n === 0 ? "Nenhum item no pedido" : n + (n === 1 ? " item no pedido" : " itens no pedido");
      btn.disabled = n === 0;
    };
    menu.addEventListener("click", function (e) {
      var b = e.target.closest("[data-step]");
      if (!b) return;
      var q = b.parentNode.querySelector("[data-qty]");
      q.textContent = Math.max(0, Math.min(20, Number(q.textContent) + Number(b.getAttribute("data-step"))));
      update();
    });
    btn.addEventListener("click", function () {
      var lines = [];
      menu.querySelectorAll("[data-item]").forEach(function (it) {
        var n = Number(it.querySelector("[data-qty]").textContent);
        if (n) lines.push(n + "x " + it.getAttribute("data-item"));
      });
      send(menu, "Olá! Quero fazer um pedido:\n" + lines.join("\n"));
    });
    update();
  }

  /* agendamento: serviço + dia + período */
  var form = document.querySelector("[data-booking]");
  if (form) form.addEventListener("submit", function (e) {
    e.preventDefault();
    var f = new FormData(form), day = f.get("dia");
    var when = day ? day.split("-").reverse().join("/") : "o melhor dia para vocês";
    send(form, "Olá! Quero agendar: " + f.get("servico") + ".\nDia: " + when + "\nPeríodo: " + f.get("periodo") + (f.get("nome") ? "\nNome: " + f.get("nome") : ""));
  });
})();
