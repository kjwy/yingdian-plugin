(function () {
  const $ = (s) => document.querySelector(s);
  const api = async (p, body) => (await fetch(p, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {})).json();
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function itemHtml(it, showUnlock) {
    const td = it.tag_decoded || {};
    const raw = it.tag_raw || "";
    const chips = [];
    const push = (v) => { if (v && !chips.includes(v)) chips.push(v); };
    push(td.resolution);
    if (td.source) push(td.source);
    push(td.hdr);
    push(td.audio_codec);
    if (it.has_chinese_subtitle || /中字|内封/.test(raw)) push("中字");
    ["REMUX", "BluRay", "WEB-DL", "10BIT", "MKV", "MP4", "ISO", "24fps", "60fps"].forEach((k) => {
      if (raw.includes(k)) push(k);
    });
    const size = it.total_size_human || it.size || "";
    const cost = it.unlock_cost != null ? Number(it.unlock_cost) : 0;
    const isFree = cost === 0;
    const unlocked = !!it.is_unlocked;
    const chipsHtml = chips.slice(0, 7).map((c) => `<span class="chip">${esc(c)}</span>`).join("");
    const kindMap = { "115": "115", ed2k: "ED2K 离线", magnet: "磁力", offline: "115 离线" };
    const kindKey = (it.share_kind || "115").toLowerCase();
    const kindLabel = kindMap[kindKey] || kindKey.toUpperCase();
    const actionText = kindKey === "115" ? "解锁并转存" : "解锁并获取链接";
    const episode = it.episode || "";
    let libraryText = "";
    if (it.library_checked) {
      if (!it.library_exists) {
        libraryText = "未入库";
      } else if (it.media_type === "movie") {
        libraryText = "已入库";
      } else if (it.pending_episodes_text && !it.in_library && !it.new_episodes_text) {
        libraryText = "转存处理中 " + it.pending_episodes_text;
      } else if (it.already_complete) {
        libraryText = "已完整入库" + (it.library_available_text ? " " + it.library_available_text : "");
      } else if (it.new_episodes_text) {
        libraryText = (it.library_available_text ? "已入库 " + it.library_available_text + " · " : "") + "可补 " + it.new_episodes_text;
      } else {
        libraryText = "已入库";
      }
    }
    const disabled = !!it.already_complete;
    return `<div class="share-row" data-json="${encodeURIComponent(JSON.stringify(it))}">
      <div class="sr-main">
        <div class="sr-chips">
          <span class="chip chip-kind kind-${esc(kindKey)}">${esc(kindLabel)}</span>
          ${episode ? `<span class="chip chip-ep">${esc(episode)}</span>` : ""}
          ${chipsHtml || '<span class="chip">未知规格</span>'}
        </div>
        <div class="sr-meta">
          <span class="sr-size">💾 ${esc(size || "-")}</span>
          <span class="sr-cost ${isFree ? "free" : ""}">${isFree ? "免费" : "⭐ " + cost + " 积分"}</span>
          ${unlocked ? '<span class="sr-done">已解锁</span>' : ""}
          ${libraryText ? `<span class="sr-library ${disabled ? "done" : ""}">📚 ${esc(libraryText)}</span>` : ""}
        </div>
        <div class="sr-raw" title="${esc(raw)}">${esc(raw)}</div>
      </div>
      ${showUnlock ? `<button class="btn primary sm act-unlock" ${disabled ? "disabled" : ""}>${disabled ? "无需重复转存" : actionText}</button>` : ""}
    </div>`;
  }

  function bindUnlock(box, title) {
    box.querySelectorAll(".act-unlock").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const rowEl = btn.closest(".share-row") || btn.parentNode;
        const it = JSON.parse(decodeURIComponent(rowEl.getAttribute("data-json")));
        const actionText = (it.share_kind || "115") === "115" ? "解锁并转存" : "解锁并获取链接";
        btn.disabled = true;
        const t0 = Date.now();
        const box = rowEl.querySelector(".unlock-progress") || (() => {
          const d = document.createElement("div");
          d.className = "unlock-progress";
          rowEl.appendChild(d);
          return d;
        })();
        const timer = setInterval(() => {
          const s = Math.round((Date.now() - t0) / 1000);
          box.textContent = `解锁中… ${s}s · 通常 15-60 秒`;
        }, 1000);
        btn.textContent = "解锁中…";
        let r;
        try {
          r = await api("/api/unlock", Object.assign({}, it, { title }));
        } catch (err) {
          clearInterval(timer);
          box.textContent = "请求失败：" + err.message;
          btn.textContent = actionText;
          btn.disabled = false;
          return;
        }
        clearInterval(timer);
        const secs = Math.round((Date.now() - t0) / 1000);
        if (r.ok) {
          const link = r.link || r.url_115 || "";
          box.innerHTML = `✅ ${secs}s ${esc(r.message || "已解锁")}`
            + (link ? `<br><span class="sr-raw" style="user-select:all">${esc(link)}</span>` : "");
          box.style.color = "#34d399";
        } else {
          box.textContent = `❌ ${secs}s：${r.message || "失败"}`;
          box.style.color = "#f87171";
        }
        btn.textContent = r.ok ? ((it.share_kind || "115") === "115" ? "已转存 ✓" : "链接已获取 ✓") : "重试";
        btn.disabled = r.ok;
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
      tgResult("请求失败：" + err.message, false);
      btn.textContent = old;
    } finally {
      btn.disabled = false;
    }
  }
  $("#btn-tg-check")?.addEventListener("click", (e) => tgCall("/api/telegram/check", e.currentTarget, "诊断中…", "连接正常 ✓"));

  // noVNC 入口（同主机 6080 端口）
  (function () {
    const a = $("#novnc-link");
    if (a) {
      const host = location.hostname || "127.0.0.1";
      a.href = location.protocol + "//" + host + ":6080/vnc.html";
    }
  })();

  // 运行模式诊断
  $("#btn-client-check")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget, old = btn.textContent;
    const box = $("#client-check-msg");
    btn.disabled = true; btn.textContent = "诊断中…";
    try {
      const r = await (await fetch("/api/client/check", { method: "POST" })).json();
      if (box) { box.textContent = (r.ok ? "✅ " : "❌ ") + (r.message || ""); box.style.color = r.ok ? "#34d399" : "#f87171"; }
      btn.textContent = r.ok ? "已就绪 ✓" : old;
    } catch (err) {
      if (box) { box.textContent = "❌ 请求失败：" + err.message; box.style.color = "#f87171"; }
      btn.textContent = old;
    } finally { btn.disabled = false; }
  });

  // Emby 入库检测
  $("#btn-emby-check")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget, old = btn.textContent;
    const box = $("#emby-check-msg");
    btn.disabled = true; btn.textContent = "检测中…";
    try {
      const r = await (await fetch("/api/emby/check", { method: "POST" })).json();
      if (box) { box.textContent = (r.ok ? "✅ " : "❌ ") + (r.message || ""); box.style.color = r.ok ? "#34d399" : "#f87171"; }
      btn.textContent = r.ok ? "连接正常 ✓" : old;
    } catch (err) {
      if (box) { box.textContent = "❌ 请求失败：" + err.message; box.style.color = "#f87171"; }
      btn.textContent = old;
    } finally { btn.disabled = false; }
  });

  // 列出 115 文件夹并选择
  $("#btn-115-folders")?.addEventListener("click", async (e) => {
    const b = e.currentTarget, old = b.textContent;
    b.disabled = true; b.textContent = "查询中…";
    try {
      const r = await (await fetch("/api/115/folders?cid=0")).json();
      const sel = $("#d115-folder-pick");
      if (!r.ok) {
        alert(r.message || "查询失败");
        b.textContent = old; b.disabled = false; return;
      }
      sel.innerHTML = '<option value="">— 根目录(0) —</option>' +
        (r.folders || []).map(f => `<option value="${f.cid}">${f.name}</option>`).join("");
      sel.style.display = "block";
      sel.onchange = () => {
        const v = sel.value || "0";
        const inp = $("#d115-cid");
        if (inp) inp.value = v;
      };
      b.textContent = `找到 ${r.folders.length} 个文件夹`;
    } catch (err) { alert("请求失败：" + err.message); b.textContent = old; }
    b.disabled = false;
  });

  // ===== 搜索结果缓存恢复（切到设置页再回来还在）=====
  (function restoreSearchCache() {
    if (!document.getElementById("search-result")) return;   // 只在仪表盘
    try {
      const raw = localStorage.getItem("yd_search_cache");
      if (!raw) return;
      const c = JSON.parse(raw);
      if (!c || !c.items || !c.items.length) return;
      const qEl = $("#q-tmdb");
      const tEl = $("#q-type");
      const sEl = $("#q-season");
      if (qEl) qEl.value = c.tmdb_id || "";
      if (tEl) tEl.value = c.media_type || "";
      if (sEl) sEl.value = c.season || "";
      const box = $("#search-result");
      const ago = Math.max(1, Math.round((Date.now() - (c.ts || Date.now())) / 60000));
      box.innerHTML = `<div class="item"><span class="m">📌 上次结果 · ${ago} 分钟前 · ${c.items.length} 条 · 点“查询资源”刷新</span></div>`
        + mediaSummary(c.media)
        + librarySummary(c.library)
        + (c.resolved_title ? `<div class="item"><span class="m">已匹配：${esc(c.resolved_title)} · TMDB ${esc(c.tmdb_id_resolved)}</span></div>` : "")
        + c.items.map((it) => itemHtml(it, true)).join("");
      bindUnlock(box, c.resolved_title || ("TMDB " + (c.tmdb_id_resolved || "")));
    } catch (e) {}
  })();

  // 滚动位置记忆
  (function scrollMemory() {
    const key = "yd_scroll_" + location.pathname;
    const y = sessionStorage.getItem(key);
    if (y) window.scrollTo(0, parseInt(y, 10) || 0);
    window.addEventListener("beforeunload", () => sessionStorage.setItem(key, String(window.scrollY)));
  })();

  // 测试 115 Cookie
  $("#btn-115-check")?.addEventListener("click", async (e) => {
    const b = e.currentTarget, old = b.textContent;
    const box = $("#d115-check-msg");
    b.disabled = true; b.textContent = "检测中…";
    try {
      const r = await (await fetch("/api/115/check", { method: "POST" })).json();
      if (box) { box.textContent = (r.ok ? "✅ " : "❌ ") + (r.message || ""); box.style.color = r.ok ? "#34d399" : "#f87171"; }
      b.textContent = r.ok ? "Cookie 有效 ✓" : old;
    } catch (err) {
      if (box) { box.textContent = "❌ 请求失败：" + err.message; box.style.color = "#f87171"; }
      b.textContent = old;
    } finally { b.disabled = false; }
  });

  // Telegram 账号登录（userbot）
  function ubMsg(text, ok) {
    const box = $("#tg-userbot-msg");
    if (!box) return;
    box.textContent = (ok === true ? "✅ " : ok === false ? "❌ " : "") + text;
    box.style.color = ok === true ? "#34d399" : ok === false ? "#f87171" : "#9aa7bd";
  }
  $("#btn-tg-sendcode")?.addEventListener("click", async (e) => {
    const b = e.currentTarget; b.disabled = true; b.textContent = "发送中…";
    try {
      const r = await (await fetch("/api/tg/userbot/start", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: $("#tg-phone").value.trim() }),
      })).json();
      ubMsg(r.message || "", r.ok);
    } catch (err) { ubMsg("请求失败：" + err.message, false); }
    b.textContent = "1. 发送验证码"; b.disabled = false;
  });
  $("#btn-tg-verify")?.addEventListener("click", async (e) => {
    const b = e.currentTarget; b.disabled = true; b.textContent = "登录中…";
    try {
      const r = await (await fetch("/api/tg/userbot/verify", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone: $("#tg-phone").value.trim(),
          code: $("#tg-code").value.trim(),
          password: $("#tg-password").value.trim(),
        }),
      })).json();
      ubMsg(r.message || (r.ok ? "登录成功" : "登录失败"), r.ok);
      if (r.ok) b.textContent = "已登录 ✓";
    } catch (err) { ubMsg("请求失败：" + err.message, false); }
    b.disabled = false;
    if (!b.textContent.includes("✓")) b.textContent = "2. 登录";
  });

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
    const b = e.currentTarget, old = b.textContent;
    const box = $("#checkin-msg");
    const t0 = Date.now();
    b.disabled = true;
    const timer = setInterval(() => {
      const sec = Math.round((Date.now() - t0) / 1000);
      b.textContent = `签到中 ${sec}s`;
      if (box) box.textContent = "浏览器模式需要打开影癫签到页，通常 15-30 秒…";
    }, 1000);
    try {
      const r = await api("/api/checkin");
      clearInterval(timer);
      const sec = Math.round((Date.now() - t0) / 1000);
      if (box) {
        box.textContent = (r.ok ? "✅ " : "❌ ") + (r.message || "") + ` · ${sec}s`;
        box.style.color = r.ok ? "#34d399" : "#f87171";
      }
      b.textContent = r.ok ? "已签到 ✓" : old;
      if (r.ok) { b.disabled = true; setTimeout(() => location.reload(), 1500); }
      else b.disabled = false;
    } catch (err) {
      clearInterval(timer);
      if (box) { box.textContent = "❌ 请求失败：" + err.message; box.style.color = "#f87171"; }
      b.textContent = old; b.disabled = false;
    }
  });

  // 从榜单跳转过来：?tmdb_id=xxx 自动搜索
  (function autoSearchFromQuery() {
    const params = new URLSearchParams(location.search);
    const tid = params.get("tmdb_id");
    const directQuery = params.get("q");
    if (!tid && !directQuery) return;
    const q = $("#q-tmdb");
    if (!q) return;
    q.value = tid || directQuery;
    const typeEl = $("#q-type");
    const mediaType = params.get("media_type");
    if (typeEl && ["movie", "tv"].includes(mediaType)) typeEl.value = mediaType;
    const seasonEl = $("#q-season");
    if (seasonEl) seasonEl.value = params.get("season") || "";
    setTimeout(() => { document.getElementById("btn-search")?.click(); }, 300);
  })();

  // 手动搜索
  function mediaSummary(media) {
    if (!media || !media.title) return "";
    return `<div class="media-summary">
      ${media.poster ? `<img src="${esc(media.poster)}" alt="${esc(media.title)}">` : ""}
      <div class="media-summary-main">
        <strong>${esc(media.title)}</strong>
        <span>${esc(media.year || "")}${media.rating ? ` · ★ ${esc(media.rating)}` : ""} · ${media.media_type === "tv" ? "剧集" : "电影"}</span>
        ${media.overview ? `<small>${esc(media.overview)}</small>` : ""}
      </div>
    </div>`;
  }

  function librarySummary(lib) {
    if (!lib || !lib.checked) return "";
    if (!lib.exists) return '<div class="item"><span class="m">📚 媒体库：未入库</span></div>';
    if (lib.media_type === "tv") {
      const available = lib.available_text ? `已入库 ${lib.available_text}` : "已入库";
      const extra = lib.complete ? " · 已完整" : (lib.missing_text ? ` · 缺 ${lib.missing_text}` : "");
      return `<div class="item"><span class="m">📚 媒体库：${esc(available + extra)}</span></div>`;
    }
    return '<div class="item"><span class="m">📚 媒体库：已入库</span></div>';
  }

  $("#btn-search")?.addEventListener("click", async () => {
    const tmdb_id = $("#q-tmdb").value.trim();
    const media_type = $("#q-type") ? $("#q-type").value : "";
    const season = $("#q-season").value.trim();
    const box = $("#search-result");
    if (!tmdb_id) return;
    box.innerHTML = '<div class="item"><span class="m">查询中… 约 5-10 秒</span></div>';
    let r;
    try {
      r = await api("/api/search", { tmdb_id, media_type, season });
    } catch (err) {
      box.innerHTML = `<div class="item"><span class="m" style="color:#f87171">❌ 请求失败：${esc(err.message)}</span></div>`;
      return;
    }
    if (!r.ok) { box.innerHTML = `<div class="item"><span class="m" style="color:#f87171">❌ ${esc(r.message)}</span></div>`; return; }
    if (!r.items.length) { box.innerHTML = '<div class="item"><span class="m">影癫上没有可解锁资源</span></div>'; return; }
    // 缓存本次搜索结果（切页面回来还在）
    try {
      localStorage.setItem("yd_search_cache", JSON.stringify({
        tmdb_id, media_type, season, items: r.items,
        resolved_title: r.resolved_title || "", tmdb_id_resolved: r.tmdb_id,
        media: r.media || null, library: r.library || null, ts: Date.now(),
      }));
    } catch (e) {}

    box.innerHTML = mediaSummary(r.media) + librarySummary(r.library) + (r.resolved_title
      ? `<div class="item"><span class="m">已匹配：${esc(r.resolved_title)} · TMDB ${esc(r.tmdb_id)}</span></div>`
      : "") + r.items.map((it) => itemHtml(it, true)).join("");
    bindUnlock(box, r.resolved_title || ("TMDB " + r.tmdb_id));
    return;
  });

  // 执行订阅搜索
  ["#btn-subs-run", "#btn-subs-run2"].forEach((sel) => {
    $(sel)?.addEventListener("click", async (e) => {
      const b = e.currentTarget;
      b.disabled = true;
      const t0 = Date.now();
      const timer = setInterval(() => {
        b.textContent = `执行中… ${Math.round((Date.now() - t0) / 1000)}s`;
      }, 1000);
      let r;
      try {
        r = await api("/api/subs/run");
      } catch (err) {
        clearInterval(timer);
        b.textContent = "执行失败";
        b.disabled = false;
        alert("请求失败：" + err.message);
        return;
      }
      clearInterval(timer);
      const list = r.results || [];
      const ok = list.filter((x) => x.ok).length;
      b.textContent = `完成 · 成功 ${ok}/${list.length}`;

      // 显示每条结果的原因
      let box = document.getElementById("subs-run-result");
      if (!box) {
        box = document.createElement("div");
        box.id = "subs-run-result";
        box.className = "results";
        b.parentNode.parentNode.appendChild(box);
      }
      box.innerHTML = list.length
        ? list.map((x) => `<div class="item"><span class="t">${esc(x.title || "")}</span>
             <span class="m" style="color:${x.ok ? "#34d399" : "#f87171"}">${x.ok ? "✅ " : "❌ "}${esc(x.message || "")}</span></div>`).join("")
        : '<div class="item"><span class="m">没有启用的订阅</span></div>';

      setTimeout(() => { b.textContent = "执行订阅搜索"; b.disabled = false; }, 3000);
    });
  });

  // 添加订阅弹窗
  (function subscriptionModal() {
    const modal = $("#sub-modal");
    if (!modal) return;
    const typeEl = $("#sub-type");
    const titleEl = $("#sub-title");
    const tmdbEl = $("#sub-tmdb");
    const resultEl = $("#sub-tmdb-results");
    const open = (type) => {
      if (typeEl && ["movie", "tv"].includes(type)) typeEl.value = type;
      modal.classList.add("show");
      modal.setAttribute("aria-hidden", "false");
      document.body.classList.add("modal-open");
      setTimeout(() => titleEl?.focus(), 80);
    };
    const close = () => {
      modal.classList.remove("show");
      modal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("modal-open");
    };
    $("#open-sub-modal")?.addEventListener("click", (e) => open(e.currentTarget.dataset.type));
    $("#close-sub-modal")?.addEventListener("click", close);
    $("#cancel-sub-modal")?.addEventListener("click", close);
    modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });

    async function selectTmdb(item) {
      titleEl.value = item.title || "";
      tmdbEl.value = item.tmdb_id || "";
      typeEl.value = item.media_type || "movie";
      resultEl.innerHTML = `<div class="item"><span class="t">${esc(item.title)}</span><span class="m">已选择 · TMDB ${esc(item.tmdb_id)}</span></div>`;
      const seasonInput = modal.querySelector('[name="season"]');
      const totalInput = modal.querySelector('[name="total_episodes"]');
      try {
        const d = await api(`/api/tmdb/detail?tmdb_id=${encodeURIComponent(item.tmdb_id)}&media_type=${encodeURIComponent(item.media_type || "movie")}&season=${encodeURIComponent(seasonInput?.value || 1)}`);
        if (d.total_episodes && totalInput) totalInput.value = d.total_episodes;
      } catch (e) {}
    }

    $("#btn-sub-tmdb")?.addEventListener("click", async () => {
      const q = titleEl.value.trim();
      if (!q) { titleEl.focus(); return; }
      resultEl.innerHTML = '<div class="item"><span class="m">搜索 TMDB…</span></div>';
      try {
        const r = await api("/api/tmdb/search", { q, media_type: typeEl.value });
        if (!r.items?.length) {
          resultEl.innerHTML = '<div class="item"><span class="m">没有找到 TMDB 条目</span></div>';
          return;
        }
        resultEl.innerHTML = r.items.map((it, idx) => `<div class="item">
          <span class="t">${esc(it.title)}</span>
          <span class="m">${esc(it.year || "")} · TMDB ${esc(it.tmdb_id)} · ${it.media_type === "tv" ? "电视剧" : "电影"}</span>
          <button type="button" class="btn sm act-pick-tmdb" data-index="${idx}">选择</button>
        </div>`).join("");
        resultEl.querySelectorAll(".act-pick-tmdb").forEach((btn) => {
          btn.addEventListener("click", () => selectTmdb(r.items[Number(btn.dataset.index)]));
        });
      } catch (e) {
        resultEl.innerHTML = `<div class="item"><span class="m">搜索失败：${esc(e.message)}</span></div>`;
      }
    });
  })();

  // 兼容旧版 TMDB 搜索
  $("#btn-tmdb")?.addEventListener("click", async () => {
    const q = $("#tmdb-q").value.trim();
    const media_type = $("#tmdb-type").value;
    const box = $("#tmdb-results");
    if (!q) return;
    box.innerHTML = '<div class="item"><span class="m">搜索中…</span></div>';
    const r = await api("/api/tmdb/search", { q, media_type });
    if (!r.items.length) {
      box.innerHTML = '<div class="item"><span class="m">没有结果 · 请在设置里填 TMDB API Key</span></div>';
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

