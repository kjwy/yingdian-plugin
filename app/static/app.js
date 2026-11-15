(function () {
  const $ = (s) => document.querySelector(s);
  const api = async (p, body) => (await fetch(p, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {})).json();
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function itemHtml(it, showUnlock) {
    const tag = it.tag_raw || (it.tag_decoded ? Object.values(it.tag_decoded).filter(Boolean).join(" ") : "");
    const size = it.total_size_human || it.size || "";
    const cost = it.unlock_cost != null ? it.unlock_cost : "";
    return `<div class="item" data-json="${encodeURIComponent(JSON.stringify(it))}">
      <span class="t">${esc(tag || "未知规格")}</span>
      <span class="m">${esc(size)}</span>
      <span class="m">积分 ${esc(cost)}</span>
      ${showUnlock ? '<button class="btn primary sm act-unlock">解锁并推送</button>' : ""}
    </div>`;
  }

  function bindUnlock(box, title) {
    box.querySelectorAll(".act-unlock").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const it = JSON.parse(decodeURIComponent(btn.parentNode.getAttribute("data-json")));
        btn.disabled = true;
        btn.textContent = "解锁中…";
        const r = await api("/api/unlock", Object.assign({}, it, { title }));
        btn.textContent = r.ok ? "已推送 ✓" : (r.message || "失败");
        if (r.ok) btn.classList.remove("primary");
        btn.disabled = true;
      });
    });
  }

  // Telegram 诊断 / 测试
  function tgResult(text, ok) {
    const box = $("#tg-test-msg");
    if (!box) return;
    box.textContent = (ok ? "✅ " : "❌ ") + text;
    box.style.color = ok ? "#34d399" : "#f87171";
  }
  async function tgCall(url, btn, busyText, okText) {
    const old = btn.textContent;
    btn.disabled = true; btn.textContent = busyText;
    try {
      const resp = await fetch(url, { method: "POST" });
      const r = await resp.json();
      tgResult(r.message || ("HTTP " + resp.status), r.ok);
      btn.textContent = r.ok ? okText : old;
    } catch (err) {
      tgResult("请求失败：" + err.message + "（后端未响应？）", false);
      btn.textContent = old;
    } finally {
      btn.disabled = false;
    }
  }
  $("#btn-tg-check")?.addEventListener("click", (e) => tgCall("/api/telegram/check", e.currentTarget, "诊断中…", "连接正常 ✓"));

  // TMDB 诊断
  $("#btn-tmdb-check")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget, old = btn.textContent;
    const box = $("#tmdb-check-msg");
    btn.disabled = true; btn.textContent = "诊断中…";
    try {
      const resp = await fetch("/api/tmdb/check", { method: "POST" });
      const r = await resp.json();
      if (box) { box.textContent = (r.ok ? "✅ " : "❌ ") + (r.message || ""); box.style.color = r.ok ? "#34d399" : "#f87171"; }
      btn.textContent = r.ok ? "连接正常 ✓" : old;
    } catch (err) {
      if (box) { box.textContent = "❌ 请求失败：" + err.message; box.style.color = "#f87171"; }
      btn.textContent = old;
    } finally { btn.disabled = false; }
  });
  $("#btn-tg-test")?.addEventListener("click", (e) => tgCall("/api/notify/test", e.currentTarget, "发送中…", "已发送 ✓"));

  // 手动签到
  $("#btn-checkin")?.addEventListener("click", async (e) => {
    const b = e.currentTarget; b.disabled = true;
    const r = await api("/api/checkin");
    const box = $("#checkin-msg");
    if (box) box.textContent = r.message || "";
    if (r.ok) b.textContent = "已签到 ✓";
  });

  // 手动搜索（仪表盘）
  $("#btn-search")?.addEventListener("click", async () => {
    const tmdb_id = $("#q-tmdb").value.trim();
    const media_type = $("#q-type").value;
    const season = $("#q-season").value.trim();
    const box = $("#search-result");
    if (!tmdb_id) return;
    box.innerHTML = '<div class="item"><span class="m">查询中…</span></div>';
    const r = await api("/api/search", { tmdb_id, media_type, season });
    if (!r.ok) { box.innerHTML = `<div class="item"><span class="m">${esc(r.message)}</span></div>`; return; }
    if (!r.items.length) { box.innerHTML = '<div class="item"><span class="m">没有找到可解锁资源</span></div>'; return; }
    box.innerHTML = r.items.map((it) => itemHtml(it, true)).join("");
    bindUnlock(box, "TMDB " + tmdb_id);
  });

  // 执行订阅搜索
  ["#btn-subs-run", "#btn-subs-run2"].forEach((sel) => {
    $(sel)?.addEventListener("click", async (e) => {
      const b = e.currentTarget; b.disabled = true; b.textContent = "执行中…";
      const r = await api("/api/subs/run");
      const ok = (r.results || []).filter((x) => x.ok).length;
      b.textContent = `完成（成功 ${ok}）`;
      setTimeout(() => { b.textContent = "执行订阅搜索"; b.disabled = false; }, 2500);
    });
  });

  // TMDB 搜索（订阅页）
  $("#btn-tmdb")?.addEventListener("click", async () => {
    const q = $("#tmdb-q").value.trim();
    const media_type = $("#tmdb-type").value;
    const box = $("#tmdb-results");
    if (!q) return;
    box.innerHTML = '<div class="item"><span class="m">搜索中…</span></div>';
    const r = await api("/api/tmdb/search", { q, media_type });
    if (!r.items.length) {
      box.innerHTML = '<div class="item"><span class="m">没有结果（需在设置里填 TMDB API Key）</span></div>';
      return;
    }
    box.innerHTML = r.items.map((it) => `<div class="item">
        <span class="t">${esc(it.title)}</span>
        <span class="m">${esc(it.year)} · TMDB ${esc(it.tmdb_id)}</span>
        <button class="btn sm act-add" data-tmdb="${esc(it.tmdb_id)}" data-title="${esc(it.title)}" data-type="${esc(it.media_type)}">添加订阅</button>
      </div>`).join("");
    box.querySelectorAll(".act-add").forEach((btn) => {
      btn.addEventListener("click", () => {
        const f = document.querySelector('form[action="/subs/add"]');
        f.querySelector('[name="tmdb_id"]').value = btn.dataset.tmdb;
        f.querySelector('[name="title"]').value = btn.dataset.title;
        f.querySelector('[name="media_type"]').value = btn.dataset.type;
        f.submit();
      });
    });
  });
})();

