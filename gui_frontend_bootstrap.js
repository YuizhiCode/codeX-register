    (function () {
      var appEl = document.getElementById("app");
      function renderFail(title, detail) {
        if (!appEl) return;
        appEl.innerHTML = "";

        var wrap = document.createElement("div");
        wrap.style.minHeight = "100vh";
        wrap.style.display = "flex";
        wrap.style.alignItems = "center";
        wrap.style.justifyContent = "center";
        wrap.style.padding = "24px";

        var card = document.createElement("div");
        card.style.maxWidth = "760px";
        card.style.width = "100%";
        card.style.background = "rgba(15,24,37,.94)";
        card.style.border = "1px solid #2a3a51";
        card.style.borderRadius = "14px";
        card.style.padding = "16px 18px";
        card.style.color = "#dbe7f5";
        card.style.boxShadow = "0 10px 30px rgba(0,0,0,.34)";

        var t = document.createElement("h3");
        t.textContent = title;
        t.style.margin = "0 0 8px";

        var p = document.createElement("p");
        p.textContent = detail;
        p.style.margin = "0";
        p.style.whiteSpace = "pre-wrap";
        p.style.lineHeight = "1.6";

        var tip = document.createElement("p");
        tip.textContent = "建议：1) 安装 Microsoft Edge WebView2 Runtime；2) 确认可访问 unpkg CDN；3) 也可用 --mode browser 先验证。";
        tip.style.margin = "10px 0 0";
        tip.style.fontSize = "12px";
        tip.style.color = "#8ea3bb";

        card.appendChild(t);
        card.appendChild(p);
        card.appendChild(tip);
        wrap.appendChild(card);
        appEl.appendChild(wrap);
      }

      window.__codexMounted = false;
      window.__codexRenderFail = renderFail;

      window.addEventListener("error", function (event) {
        if (window.__codexMounted) return;
        var msg = (event && event.message) ? event.message : "脚本运行异常";
        renderFail("页面加载失败", msg);
      });

      setTimeout(function () {
        if (window.__codexMounted) return;
        if (!window.Proxy) {
          renderFail("当前内核不支持", "检测到旧版 WebView 内核。请安装 Microsoft Edge WebView2 Runtime 后重试。");
          return;
        }
        if (!window.Vue || !window.naive) {
          renderFail("资源加载失败", "未能加载 Vue / Naive UI 资源，请检查网络代理或防火墙设置。\n若在公司网络，请先测试 --mode browser。");
        }
      }, 3200);
    })();
