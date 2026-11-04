/* 서무비서 AI — 화면 로직 (외부 라이브러리 없음, 오프라인 동작) */
"use strict";

// ------------------------------------------------------------------ 아이콘 (SF Symbols 느낌의 선형 아이콘)
const ICONS = {
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z"/><path d="M8.5 12h.01M12 12h.01M15.5 12h.01"/>',
  tray: '<path d="M4 13l2.5-7.5A2 2 0 0 1 8.4 4h7.2a2 2 0 0 1 1.9 1.5L20 13"/><path d="M4 13v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5h-5l-1 2h-4l-1-2H4z"/>',
  check: '<rect x="3.5" y="3.5" width="17" height="17" rx="4"/><path d="M8 12.5l2.7 2.7L16.5 9"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M3.5 7l8.5 6 8.5-6"/>',
  books: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><path d="M9 7h7M9 11h5"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
  up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
  doc: '<path d="M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.9-3.9L4 9"/><path d="M4 4v5h5"/><path d="M4 13a8 8 0 0 0 14.9 3.9L20 15"/><path d="M20 20v-5h-5"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5"/><path d="M5 20h14"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  left: '<path d="M15 6l-6 6 6 6"/>', right: '<path d="M9 6l6 6-6 6"/>',
  ok: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16.5 9"/>',
  err: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.5h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16v4z"/>',
};
const svg = (name) => `<svg viewBox="0 0 24 24">${ICONS[name] || ""}</svg>`;
function paintIcons(root = document) {
  root.querySelectorAll("i[data-icon]").forEach((el) => { if (!el.firstChild) el.innerHTML = svg(el.dataset.icon); });
}

// ------------------------------------------------------------------ 유틸
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const WD = "일월화수목금토";

async function api(name, ...args) {
  const r = await fetch("/api/" + name, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Seomu-Token": window.SEOMU_TOKEN || "" },
    body: JSON.stringify({ args }),
  });
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || "오류가 발생했습니다");
  return j.result;
}
async function runJob(name, args, onUpdate) {
  const { job_id } = await api(name, ...args);
  for (;;) {
    await sleep(350);
    const st = await api("job_status", job_id);
    onUpdate && onUpdate(st);
    if (st.status === "done") return st.result;
    if (st.status === "error") throw new Error(st.error);
  }
}
function toast(msg, kind = "info", ms = 3800) {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.innerHTML = `<i>${svg(kind === "ok" ? "ok" : kind === "err" ? "err" : "info")}</i><div>${esc(msg)}</div>`;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.style.transition = "opacity .3s"; el.style.opacity = "0"; setTimeout(() => el.remove(), 300); }, ms);
}
function hud(text) {
  if (text === false) return $("#hud").classList.add("hidden");
  $("#hud-text").textContent = text;
  $("#hud").classList.remove("hidden");
}
function ddayBadge(d) {
  if (d === null || d === undefined) return "";
  if (d < 0) return `<span class="badge red">D+${-d}</span>`;
  if (d === 0) return `<span class="badge red">D-Day</span>`;
  if (d <= 3) return `<span class="badge orange">D-${d}</span>`;
  if (d <= 7) return `<span class="badge blue">D-${d}</span>`;
  return `<span class="badge">D-${d}</span>`;
}
function fmtDate(iso, withWd = true) {
  if (!iso) return "";
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  if (isNaN(d)) return iso;
  return `${d.getMonth() + 1}월 ${d.getDate()}일` + (withWd ? ` (${WD[d.getDay()]})` : "");
}
function relTime(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const diff = (Date.now() - d) / 1000;
  if (diff < 60) return "방금";
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return `${d.getMonth() + 1}/${d.getDate()}`;
}
function extOf(name) { const m = /\.([a-z0-9]+)$/i.exec(name || ""); return m ? m[1].toLowerCase() : "file"; }
function baseName(p) { return String(p || "").split(/[\\/]/).pop(); }
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); }
  catch { const ta = document.createElement("textarea"); ta.value = t; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); }
}
function readFiles(fileList) {
  return Promise.all(Array.from(fileList).map((f) => new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res({ name: f.name, data: fr.result });
    fr.onerror = rej;
    fr.readAsDataURL(f);
  })));
}
function segmented(el, onChange) {
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    $$("button", el).forEach((x) => x.classList.toggle("on", x === b));
    onChange && onChange(b.dataset.v);
  });
}
const segValue = (el) => ($("button.on", el) || {}).dataset?.v ?? "";

// 간단한 마크다운 → HTML (굵게, 목록, 인용 번호)
function md(text) {
  const lines = esc(text).split("\n");
  let html = "", list = null;
  const inline = (s) => s
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[(\d{1,2})\]/g, '<span class="cite" data-n="$1">$1</span>');
  for (const raw of lines) {
    const l = raw.trimEnd();
    const ol = /^\s*(\d+)[.)]\s+(.*)$/.exec(l), ul = /^\s*[-*•·]\s+(.*)$/.exec(l);
    if (ol || ul) {
      const t = ol ? "ol" : "ul";
      if (list !== t) { if (list) html += `</${list}>`; html += `<${t}>`; list = t; }
      html += `<li>${inline(ol ? ol[2] : ul[1])}</li>`;
      continue;
    }
    if (list) { html += `</${list}>`; list = null; }
    if (!l.trim()) continue;
    const h = /^#{1,4}\s+(.*)$/.exec(l);
    html += h ? `<p><b>${inline(h[1])}</b></p>` : `<p>${inline(l)}</p>`;
  }
  if (list) html += `</${list}>`;
  return html;
}

// ------------------------------------------------------------------ 상태
const state = { settings: {}, info: {}, notices: [], templates: [], tasks: [], calMonth: new Date(), calSel: null, tplSel: null, pendingFiles: [] };

// ------------------------------------------------------------------ 내비게이션
function go(page) {
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + page));
  const loaders = { home: loadHome, ask: loadChat, collect: loadNotices, tasks: loadTasks, mail: loadMail, library: loadLibrary, settings: loadSettings };
  loaders[page] && loaders[page]();
}

// ------------------------------------------------------------------ AI 상태
async function refreshAI() {
  const chip = $("#ai-chip");
  try {
    const st = await api("llm_status");
    chip.classList.toggle("ok", st.ok && !!st.chat_model);
    chip.classList.toggle("bad", !(st.ok && st.chat_model));
    $(".ai-chip-text", chip).textContent = st.ok && st.chat_model ? `로컬 AI · ${st.chat_model}` : "AI 엔진 미연결 (검색 모드)";
    chip.title = st.ok ? `모델: ${st.models.join(", ") || "없음"}` : st.error || "";
    const dl = $("#model-list");
    dl.innerHTML = (st.models || []).map((m) => `<option value="${esc(m)}">`).join("");
    const s = $("#set-ai-status");
    if (s) s.textContent = st.ok ? `연결됨 · 답변 모델: ${st.chat_model || "없음"} · 임베딩: ${st.embed_model || "미사용(키워드 검색)"}` : (st.error || "연결 안 됨");
    return st;
  } catch (e) { chip.classList.add("bad"); }
}

// ------------------------------------------------------------------ 오늘
async function loadHome() {
  const d = await api("dashboard");
  const now = new Date();
  $("#home-date").textContent = `${now.getFullYear()}년 ${now.getMonth() + 1}월 ${now.getDate()}일 ${WD[now.getDay()]}요일`;
  const h = now.getHours();
  const name = state.settings.user_name ? `${state.settings.user_name}님, ` : "";
  $("#home-greet").textContent = name + (h < 12 ? "좋은 아침입니다" : h < 18 ? "좋은 오후입니다" : "오늘도 수고하셨습니다");
  $("#st-overdue").textContent = d.overdue; $("#st-today").textContent = d.due_today;
  $("#st-week").textContent = d.due_week; $("#st-open").textContent = d.open_tasks;
  $("#badge-tasks").textContent = d.overdue + d.due_today || "";
  $("#home-docs").textContent = `색인된 규정 ${d.documents}건`;
  const tasks = d.tasks.filter((t) => t.due).slice(0, 6);
  $("#home-tasks").innerHTML = tasks.length ? tasks.map((t) => `
    <li class="clickable" data-goto="tasks"><div class="main-col"><div class="t">${esc(t.title)}</div>
    <div class="s">${fmtDate(t.due)}${t.notice_title ? " · " + esc(t.notice_title) : ""}</div></div>${ddayBadge(t.dday)}</li>`).join("")
    : `<li class="empty">다가오는 기한이 없습니다 🎉</li>`;
  $("#home-notices").innerHTML = d.notices.length ? d.notices.map((n) => noticeRow(n)).join("") : `<li class="empty">수집한 공문이 없습니다</li>`;
}
function noticeRow(n) {
  const a = n.analysis || {};
  const next = (a.deadlines || []).find((x) => x.date >= new Date().toISOString().slice(0, 10)) || (a.deadlines || [])[0];
  const dd = next ? Math.round((new Date(next.date + "T00:00:00") - new Date(new Date().toDateString())) / 86400000) : null;
  const okFiles = (n.attachments || []).filter((f) => f.ok).length;
  return `<li class="clickable" data-notice="${n.id}"><div class="notice-icon">${svg("doc")}</div>
    <div class="main-col"><div class="t">${esc(a.folder_name || n.title)}</div>
    <div class="s">${relTime(n.created_at)} · 붙임 ${okFiles}건${next ? " · 기한 " + fmtDate(next.date, false) : ""}</div></div>
    ${next ? ddayBadge(dd) : ""}</li>`;
}

// ------------------------------------------------------------------ 규정 Q&A
let asking = false;
async function loadChat() {
  const hist = await api("chat_history");
  const chat = $("#chat");
  $$(".msg", chat).forEach((m) => m.remove());
  $("#chat-empty").classList.toggle("hidden", hist.length > 0);
  hist.forEach((h) => { addUserMsg(h.question); const m = addAiMsg(); finishAiMsg(m, { answer: h.answer, sources: h.sources }); });
  chat.scrollTop = chat.scrollHeight;
}
function addUserMsg(q) {
  $("#chat-empty").classList.add("hidden");
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML = `<div class="bubble">${esc(q)}</div>`;
  $("#chat").appendChild(el);
  return el;
}
function addAiMsg() {
  const el = document.createElement("div");
  el.className = "msg ai";
  el.innerHTML = `<div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div><div class="msg-meta"></div>`;
  $("#chat").appendChild(el);
  $("#chat").scrollTop = $("#chat").scrollHeight;
  return el;
}
function finishAiMsg(el, res) {
  $(".bubble", el).innerHTML = md(res.answer || "");
  const srcs = res.sources || [];
  if (srcs.length) {
    const box = document.createElement("div");
    box.className = "sources";
    box.innerHTML = srcs.map((s, i) => `<div class="source" data-n="${i + 1}">
      <div class="source-head"><span class="n">[${i + 1}]</span><span>${esc(s.title)}</span><span class="muted">${esc(s.heading || "")}</span>
      <span class="spacer"></span><span class="badge ${s.category === "법령" ? "purple" : s.category === "조례" ? "blue" : s.category === "내규" ? "green" : ""}">${esc(s.category)}</span></div>
      <div class="source-body">${esc(s.text)}</div></div>`).join("");
    el.appendChild(box);
  }
  const meta = $(".msg-meta", el);
  meta.textContent = res.mode === "llm" ? `로컬 AI 답변 · ${res.model || ""}` : res.mode === "search" ? "검색 결과 (AI 미연결)" : "";
}
async function ask(q) {
  q = (q || "").trim();
  if (!q || asking) return;
  asking = true; $("#ask-send").disabled = true;
  addUserMsg(q);
  const el = addAiMsg();
  try {
    const res = await runJob("ask", [q, segValue($("#ask-cat"))], (st) => {
      if (st.text) { $(".bubble", el).innerHTML = md(st.text); $("#chat").scrollTop = $("#chat").scrollHeight; }
      else $(".msg-meta", el).textContent = st.message || "";
    });
    finishAiMsg(el, res);
  } catch (e) {
    $(".bubble", el).innerHTML = `<p>⚠️ ${esc(e.message)}</p>`;
  } finally {
    asking = false; $("#ask-send").disabled = false;
    $("#chat").scrollTop = $("#chat").scrollHeight;
  }
}

// ------------------------------------------------------------------ 공문 수집
async function loadNotices() {
  state.notices = await api("list_notices");
  $("#notice-count").textContent = state.notices.length ? `${state.notices.length}건` : "";
  $("#badge-notices").textContent = state.notices.length || "";
  $("#notice-list").innerHTML = state.notices.length ? state.notices.map(noticeRow).join("")
    : `<li class="empty">아직 수집한 공문이 없습니다. 위에서 공문을 수집해 보세요.</li>`;
  $("#br-hint").textContent = state.info.browser_available ? "" : "※ 브라우저 연동을 쓰려면 Playwright 설치가 필요합니다 (README 참고). 주소 수집과 파일 가져오기는 바로 쓸 수 있습니다.";
}
async function doCollect(name, args) {
  hud("공문을 수집하는 중…");
  try {
    const notice = await runJob(name, args, (st) => st.message && hud(st.message));
    hud(false);
    const a = notice.analysis || {};
    toast(`정리 완료: ${a.folder_name || notice.title} · 기한 ${(a.deadlines || []).length}건 등록`, "ok");
    await loadNotices();
    openNotice(notice.id);
  } catch (e) { hud(false); toast(e.message, "err", 6000); }
}
function renderPendingFiles() {
  const ul = $("#notice-files");
  ul.innerHTML = state.pendingFiles.map((p, i) => `<li>${i === 0 ? '<span class="tag">본문</span>' : '<span class="tag" style="color:var(--text-2)">붙임</span>'}
    <span>${esc(baseName(p))}</span><span class="spacer"></span>
    ${i ? `<button class="btn ghost sm" data-main="${i}">본문으로</button>` : ""}<button class="btn ghost sm" data-rm="${i}">${svg("close")}</button></li>`).join("");
  $("#file-collect").disabled = !state.pendingFiles.length;
}

// 공문 상세 시트
let currentNotice = null;
async function openNotice(id) {
  const n = await api("get_notice", id);
  if (!n) return;
  currentNotice = n;
  const a = n.analysis || {};
  $("#nd-title").textContent = a.folder_name || n.title;
  $("#nd-date").textContent = `${n.created_at.replace("T", " ").slice(0, 16)} 수집 · ${a.mode === "llm" ? "로컬 AI 분석 (" + (a.model || "") + ")" : "규칙 기반 분석"}`;
  const today = new Date(new Date().toDateString());
  const dls = (a.deadlines || []).map((d) => {
    const dt = new Date(d.date + "T00:00:00");
    const dd = Math.round((dt - today) / 86400000);
    return `<div class="deadline"><div class="date"><div class="m">${dt.getMonth() + 1}월</div><div class="d">${dt.getDate()}</div></div>
      <div class="what"><div>${esc(d.what)}</div><div class="muted small">${fmtDate(d.date)} ${esc(d.time || "")} · ${esc(d.source || "")}</div></div>${ddayBadge(dd)}</div>`;
  }).join("") || `<div class="muted">본문에서 제출 기한을 찾지 못했습니다.</div>`;
  const subs = (a.submissions || []).map((s) => `<li><div>${esc(s.item)}${s.how || s.to ? `<div class="muted small">${esc([s.how, s.to].filter(Boolean).join(" · "))}</div>` : ""}</div></li>`).join("");
  const acts = (a.actions || []).map((x) => `<li>${esc(x)}</li>`).join("");
  const ev = a.event || {};
  const evRows = [["행사명", ev.name], ["일시", ev.date], ["장소", ev.place]].filter((r) => r[1]);
  const files = (n.attachments || []).map((f) => `<div class="attach" ${f.ok ? `data-open="${esc(f.path)}"` : ""}>
      <div class="ext ${extOf(f.name)}">${esc(extOf(f.name)).slice(0, 4)}</div>
      <div class="main-col"><div>${esc(f.name)}</div><div class="muted small">${f.ok ? "다운로드 완료 · 눌러서 열기" : "실패: " + esc(f.error || "")}</div></div></div>`).join("")
    || `<div class="muted">붙임 파일이 없습니다.</div>`;
  $("#nd-body").innerHTML = `
    <div class="section"><h4>요약</h4><div class="summary-box">${esc(a.summary || "-")}</div></div>
    <div class="section"><h4>제출 기한</h4>${dls}</div>
    <div class="grid-2">
      <div class="section"><h4>제출물</h4>${subs ? `<ul class="check-list">${subs}</ul>` : '<div class="muted">확인된 제출물 없음</div>'}</div>
      <div class="section"><h4>할 일</h4>${acts ? `<ul class="check-list">${acts}</ul>` : '<div class="muted">-</div>'}</div>
    </div>
    ${evRows.length ? `<div class="section"><h4>행사 정보</h4><dl class="kv">${evRows.map((r) => `<dt>${r[0]}</dt><dd>${esc(r[1])}</dd>`).join("")}</dl></div>` : ""}
    ${a.contact ? `<div class="section"><h4>문의처</h4><div>${esc(a.contact)}</div></div>` : ""}
    <div class="section"><h4>붙임 파일 · ${esc(baseName(n.folder))}</h4>${files}</div>
    ${a.llm_error ? `<div class="section muted small">AI 분석 불가로 규칙 기반 결과를 표시합니다: ${esc(a.llm_error)}</div>` : ""}
    <details class="raw"><summary>본문 원문 보기</summary><pre>${esc(n.body || "")}</pre></details>`;
  $("#sheet").classList.remove("hidden");
}
function closeSheet() { $("#sheet").classList.add("hidden"); }

// ------------------------------------------------------------------ 할 일
async function loadTasks() {
  const filter = segValue($("#task-filter"));
  const all = await api("list_tasks", true);
  state.tasks = all;
  const list = all.filter((t) => filter === "all" ? true : filter === "done" ? t.done : !t.done);
  $("#task-list").innerHTML = list.length ? list.map((t) => `
    <li class="${t.done ? "done" : ""}" data-id="${t.id}">
      <input type="checkbox" class="task-check" ${t.done ? "checked" : ""}>
      <div class="body"><div class="title">${esc(t.title)}</div>
        <div class="sub">${t.due ? `<span class="due ${t.dday !== null && t.dday <= 0 && !t.done ? "red" : ""}">${svg("calendar")} ${fmtDate(t.due)}</span>` : ""}
        ${t.notice_title ? `<span class="link" data-notice="${t.notice_id}">${svg("doc")} ${esc(t.notice_title.slice(0, 40))}</span>` : ""}</div></div>
      ${t.done ? "" : ddayBadge(t.dday)}
      <div class="actions"><button class="btn ghost sm" data-edit="${t.id}" title="기한 변경">${svg("edit")}</button>
      <button class="btn ghost sm danger" data-del="${t.id}" title="삭제">${svg("trash")}</button></div>
    </li>`).join("") : `<li class="empty-state">할 일이 없습니다</li>`;
  const open = all.filter((t) => !t.done && t.dday !== null && t.dday <= 0).length;
  $("#badge-tasks").textContent = open || "";
  renderCalendar();
}
function renderCalendar() {
  const m = state.calMonth, y = m.getFullYear(), mo = m.getMonth();
  $("#cal-title").textContent = `${y}년 ${mo + 1}월`;
  const first = new Date(y, mo, 1), start = new Date(y, mo, 1 - first.getDay());
  const byDate = {};
  state.tasks.filter((t) => t.due && !t.done).forEach((t) => (byDate[t.due.slice(0, 10)] ||= []).push(t));
  const todayKey = new Date().toLocaleDateString("sv-SE");
  let html = [..."일월화수목금토"].map((w) => `<div class="wd">${w}</div>`).join("");
  for (let i = 0; i < 42; i++) {
    const d = new Date(start); d.setDate(start.getDate() + i);
    const key = d.toLocaleDateString("sv-SE");
    const n = (byDate[key] || []).length;
    html += `<div class="day ${d.getMonth() !== mo ? "other" : ""} ${key === todayKey ? "today" : ""} ${key === state.calSel ? "sel" : ""}" data-date="${key}">
      ${d.getDate()}${n ? `<span class="dots">${"<b></b>".repeat(Math.min(n, 3))}</span>` : ""}</div>`;
  }
  $("#cal").innerHTML = html;
  const sel = state.calSel || todayKey;
  const items = byDate[sel] || [];
  $("#cal-day").innerHTML = `<div class="muted small" style="margin-bottom:4px">${fmtDate(sel)}</div>` +
    (items.length ? items.map((t) => `<div class="item">${svg("clock")}<span>${esc(t.title)}</span></div>`).join("") : `<div class="muted">일정 없음</div>`);
}

// ------------------------------------------------------------------ 메일
async function loadMail() {
  const r = await api("list_templates");
  state.templates = r.templates;
  state.notices = await api("list_notices");
  const cur = $("#mc-template").value;
  $("#mc-template").innerHTML = r.templates.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("");
  if (cur) $("#mc-template").value = cur;
  const curN = $("#mc-notice").value;
  $("#mc-notice").innerHTML = `<option value="">(공문 없이 양식만)</option>` + state.notices.map((n) => `<option value="${n.id}">${esc((n.analysis || {}).folder_name || n.title)}</option>`).join("");
  if (curN) $("#mc-notice").value = curN;
  $("#tpl-vars").innerHTML = r.variables.map((v) => `<button class="chip" data-var="${esc(v)}">{{${esc(v)}}}</button>`).join("");
  renderTplList();
}
function renderTplList() {
  $("#tpl-list").innerHTML = state.templates.map((t) => `<li class="${t.id === state.tplSel ? "on" : ""}" data-tpl="${t.id}">
    <div class="main-col"><div class="t">${esc(t.name)}</div><div class="s">${esc(t.subject)}</div></div></li>`).join("");
  const t = state.templates.find((x) => x.id === state.tplSel);
  $("#tpl-name").value = t ? t.name : ""; $("#tpl-subject").value = t ? t.subject : ""; $("#tpl-body").value = t ? t.body : "";
  $("#tpl-delete").disabled = !t;
}
async function makeMail() {
  const tid = $("#mc-template").value;
  if (!tid) return toast("양식을 먼저 만들어 주세요", "err");
  const nid = $("#mc-notice").value || null;
  const r = await api("render_mail", Number(tid), nid ? Number(nid) : null, {});
  $("#mc-subject").value = r.subject; $("#mc-body").value = r.body;
  $("#mc-missing").textContent = r.missing.length ? `채워지지 않은 항목: ${r.missing.map((x) => "[" + x + "]").join(", ")} — 설정의 '내 정보' 또는 본문에서 직접 수정하세요.` : "";
  $("#mc-attach").innerHTML = r.attachments.length ? `<div class="muted small" style="margin-bottom:4px">첨부할 파일 (눌러서 열기)</div>` +
    r.attachments.map((p) => `<div class="a" data-open="${esc(p)}">📎 ${esc(baseName(p))}</div>`).join("") : "";
}

// ------------------------------------------------------------------ 규정 저장소
let libPoll = null;
async function loadLibrary() {
  const r = await api("list_documents");
  $("#lib-dirs").innerHTML = r.dirs.map((d) => `<li><div class="notice-icon">${svg("folder")}</div><div class="main-col"><div class="t">${esc(baseName(d) || d)}</div><div class="s">${esc(d)}</div></div>
    <button class="btn ghost sm" data-open="${esc(d)}">열기</button>${r.dirs.length > 1 ? `<button class="btn ghost sm danger" data-rmdir="${esc(d)}">${svg("trash")}</button>` : ""}</li>`).join("");
  $("#lib-count").textContent = `${r.documents.length}건`;
  const catBadge = (c) => `<span class="badge ${c === "법령" ? "purple" : c === "조례" ? "blue" : c === "내규" ? "green" : ""}">${esc(c)}</span>`;
  $("#lib-docs").innerHTML = r.documents.length ? r.documents.map((d) => `<tr><td><b>${esc(d.title)}</b></td><td>${catBadge(d.category)}</td>
    <td>${d.n_chunks}</td><td class="muted">${esc(d.indexed_at.replace("T", " ").slice(0, 16))}</td>
    <td><button class="btn ghost sm" data-open="${esc(d.path)}">열기</button></td></tr>`).join("")
    : `<tr><td colspan="5" class="empty-state">아직 색인된 문서가 없습니다. 파일을 추가하고 '색인 갱신'을 누르세요.</td></tr>`;
  showProgress(r.progress);
}
function showProgress(p) {
  const box = $("#lib-progress");
  if (!p || !p.running) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  $("#lib-progress-text").textContent = p.current ? `색인 중: ${p.current}` : "색인 준비 중…";
  $("#lib-progress-count").textContent = `${p.done} / ${p.total}`;
  $("#lib-bar").style.width = p.total ? `${(p.done / p.total) * 100}%` : "5%";
}
async function reindex(force) {
  try {
    const res = await runJob("reindex", [force], async () => { const r = await api("list_documents"); showProgress(r.progress); });
    showProgress(null);
    if (res.ok === false) return toast(res.error, "err");
    toast(`색인 완료 · 새로 색인 ${res.added}건 / 변경 없음 ${res.skipped}건`, "ok");
    if (res.errors && res.errors.length) toast(`읽지 못한 파일 ${res.errors.length}건: ${res.errors.slice(0, 2).join(" / ")}`, "err", 8000);
    loadLibrary();
  } catch (e) { toast(e.message, "err"); showProgress(null); }
}
async function importLibFiles(paths) {
  if (!paths.length) return;
  try {
    const r = await api("import_regulations", paths);
    toast(`${r.copied.length}개 파일을 저장소에 추가했습니다. 색인을 시작합니다.`, "ok");
    const res = await (async () => { for (;;) { await sleep(400); const st = await api("job_status", r.job_id); const d = await api("list_documents"); showProgress(d.progress); if (st.status !== "running") return st; } })();
    if (res.status === "error") toast(res.error, "err"); else toast("색인 완료", "ok");
    loadLibrary();
  } catch (e) { toast(e.message, "err"); }
}

// ------------------------------------------------------------------ 설정
const SETTING_KEYS = ["ollama_url", "chat_model", "embed_model", "top_k", "temperature", "allow_remote_llm", "download_root", "browser_channel", "user_name", "user_dept", "user_phone", "user_email"];
async function loadSettings() {
  const s = await api("get_settings");
  state.settings = s;
  SETTING_KEYS.forEach((k) => { const el = $("#set-" + k); if (!el) return; if (el.type === "checkbox") el.checked = !!s[k]; else el.value = s[k] ?? ""; });
  $$("#set-theme button").forEach((b) => b.classList.toggle("on", b.dataset.v === (s.theme || "system")));
  $("#set-root-hint").textContent = `현재: ${s._download_root}`;
  $("#set-home").textContent = s._home;
  refreshAI();
  loadModels();
}
function applyTheme(t) {
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
}
async function saveSettings() {
  const v = {};
  SETTING_KEYS.forEach((k) => { const el = $("#set-" + k); if (!el) return; v[k] = el.type === "checkbox" ? el.checked : el.value; });
  v.theme = segValue($("#set-theme")) || "system";
  if (v.allow_remote_llm && !confirm("외부 AI 주소를 허용하면 질문과 문서 내용이 이 PC 밖으로 전송될 수 있습니다. 계속할까요?")) return;
  try {
    state.settings = await api("save_settings", v);
    applyTheme(v.theme);
    toast("설정을 저장했습니다", "ok");
    loadSettings();
  } catch (e) { toast(e.message, "err"); }
}

// ------------------------------------------------------------------ AI 모델
let ggufTarget = null, modelBusy = false;
async function loadModels() {
  let c;
  try { c = await api("model_catalog"); } catch (e) { $("#model-grid").innerHTML = `<div class="muted">${esc(e.message)}</div>`; return; }
  const si = c.system, rec = c.recommend;
  const recName = (c.models.find((m) => m.id === rec.model) || {}).name || rec.model;
  $("#pc-box").innerHTML = `<div class="specs"><b>내 PC</b> · ${esc(si.cpu)} (${si.cores}스레드)<br>
    메모리 <b>${si.ram_total_gb}GB</b> (현재 여유 ${si.ram_avail_gb}GB) · 디스크 여유 ${si.disk_free_gb}GB ·
    GPU ${si.gpu ? esc(si.gpu.split(",")[0]) + (si.gpu_usable ? " (AI 가속 가능)" : " (AI 가속 불가)") : "AI 가속 불가 · CPU 사용"}</div>
    <div class="rec"><span class="badge green">추천</span> <b>${esc(recName)}</b><div class="muted small">${esc(rec.reason)}</div>
    ${rec.warn ? `<div class="small" style="color:var(--orange);margin-top:4px">⚠ ${esc(rec.warn)}</div>` : ""}</div>`;
  if (!c.engine_ok) {
    $("#model-grid").innerHTML = `<div class="muted">로컬 AI 엔진(Ollama)이 실행 중이 아닙니다. Ollama를 설치·실행한 뒤 '다시 확인'을 눌러 주세요.<br><span class="small">${esc(c.engine_error)}</span></div>`;
    return;
  }
  $("#model-grid").innerHTML = c.models.map((m) => `
    <div class="model-card ${m.active ? "active" : ""}">
      <div class="top"><span class="name">${esc(m.name)}</span><span class="vendor">${esc(m.vendor)}</span><span class="spacer"></span>
        ${m.id === rec.model ? '<span class="badge green">내 PC 추천</span>' : ""}<span class="badge ${m.kind === "embed" ? "purple" : "blue"}">${esc(m.badge)}</span></div>
      <div class="desc">${esc(m.desc)}</div>
      <div class="meta"><span class="badge">약 ${m.download_gb}GB</span><span class="badge">RAM ${m.min_ram_gb}GB+</span>
        <span class="badge">${esc(m.license)}</span><span class="badge">${esc(m.korean)}</span>${m.variant ? `<span class="badge green">${esc(m.variant)}</span>` : ""}
        ${m.installed && m.installed_id !== m.id && m.installed_id !== m.id + ":latest" ? `<span class="badge">설치됨: ${esc(m.installed_id)}</span>` : ""}</div>
      ${m.fits ? "" : '<div class="warn">⚠ 이 PC 메모리로는 느리거나 실행되지 않을 수 있습니다</div>'}
      <div class="actions">
        ${m.installed
          ? (m.active ? `<span class="badge green">${m.kind === "embed" ? "검색에 사용 중" : "사용 중"}</span>` : `<button class="btn primary sm" data-use="${esc(m.installed_id)}">사용</button>`) +
            `<button class="btn ghost sm danger" data-mdel="${esc(m.installed_id)}" title="${esc(m.installed_id)} 삭제">${svg("trash")}</button>`
          : m.install === "gguf"
            ? `<button class="btn sm" data-gguf="${esc(m.id)}">${svg("download")} GGUF 등록</button>`
            : `<button class="btn sm" data-pull="${esc(m.id)}">${svg("download")} 받기</button>`}
      </div>
    </div>`).join("");
  $("#model-others").textContent = c.others.length ? `기타 설치된 모델: ${c.others.join(", ")} (아래 '직접 입력'으로 사용)` : "";
  const s = await api("get_settings");
  state.settings = s;
  $("#set-chat_model").value = s.chat_model || ""; $("#set-embed_model").value = s.embed_model || "";
}
async function modelJob(name, args, doneMsg) {
  if (modelBusy) return toast("다른 모델 작업이 진행 중입니다", "info");
  modelBusy = true;
  const box = $("#model-progress"); box.classList.remove("hidden");
  $("#model-bar").style.width = "2%";
  try {
    await runJob(name, args, (st) => {
      $("#model-progress-text").textContent = st.message || "진행 중…";
      const [d, t] = (st.text || "0/0").split("/").map(Number);
      if (t) $("#model-bar").style.width = `${Math.max(2, (d / t) * 100)}%`;
    });
    toast(doneMsg, "ok");
    $("#gguf-box").classList.add("hidden");
  } catch (e) { toast(e.message, "err", 8000); }
  finally { modelBusy = false; box.classList.add("hidden"); loadModels(); refreshAI(); }
}

// ------------------------------------------------------------------ 드래그 & 드롭
function setupDrop(zone, onPaths) {
  ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
  zone.addEventListener("drop", async (e) => {
    const files = e.dataTransfer.files;
    if (!files.length) return;
    hud("파일을 불러오는 중…");
    try { onPaths(await api("upload_files", await readFiles(files))); } catch (er) { toast(er.message, "err"); } finally { hud(false); }
  });
}
async function pickFiles(multiple = true) {
  if (state.info.native) return api("pick_files", multiple);
  return new Promise((resolve) => {
    const inp = document.createElement("input");
    inp.type = "file"; inp.multiple = multiple;
    inp.onchange = async () => {
      hud("파일을 불러오는 중…");
      try { resolve(await api("upload_files", await readFiles(inp.files))); } catch (e) { toast(e.message, "err"); resolve([]); } finally { hud(false); }
    };
    inp.click();
  });
}

// ------------------------------------------------------------------ 이벤트 바인딩
function bind() {
  document.addEventListener("click", async (e) => {
    const t = e.target;
    const nav = t.closest(".nav-item"); if (nav) return go(nav.dataset.page);
    const g = t.closest("[data-goto]"); if (g && !t.closest("[data-notice]")) return go(g.dataset.goto);
    const n = t.closest("[data-notice]"); if (n) return openNotice(Number(n.dataset.notice));
    const o = t.closest("[data-open]"); if (o) { const ok = await api("open_path", o.dataset.open); if (!ok) toast("파일을 열 수 없습니다", "err"); return; }
    const cite = t.closest(".cite");
    if (cite) {
      const src = $(`.source[data-n="${cite.dataset.n}"]`, cite.closest(".msg"));
      if (src) { src.classList.add("open", "flash"); src.scrollIntoView({ behavior: "smooth", block: "nearest" }); setTimeout(() => src.classList.remove("flash"), 1200); }
      return;
    }
    const src = t.closest(".source"); if (src) return src.classList.toggle("open");
  });

  // 오늘
  $("#home-ask-form").addEventListener("submit", (e) => { e.preventDefault(); const q = $("#home-ask").value; $("#home-ask").value = ""; go("ask"); ask(q); });
  $("#ai-chip").addEventListener("click", () => go("settings"));

  // Q&A
  segmented($("#ask-cat"));
  $("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); const q = $("#ask-input").value; $("#ask-input").value = ""; autoGrow(); ask(q); });
  const ta = $("#ask-input");
  const autoGrow = () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 160) + "px"; };
  ta.addEventListener("input", autoGrow);
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#ask-form").requestSubmit(); } });
  $("#ask-suggest").addEventListener("click", (e) => { const c = e.target.closest(".chip"); if (c) ask(c.textContent); });
  $("#ask-clear").addEventListener("click", async () => { if (confirm("대화 기록을 지울까요?")) { await api("clear_chat"); loadChat(); } });

  // 공문 수집
  segmented($("#collect-mode"), (v) => $$(".mode-pane").forEach((p) => p.classList.toggle("on", p.dataset.mode === v)));
  const title = () => $("#collect-title").value;
  const useAI = () => $("#collect-ai").checked;
  $("#br-open").addEventListener("click", async () => {
    hud("브라우저를 여는 중…");
    try { const r = await api("browser_open", $("#br-url").value); toast(`브라우저가 열렸습니다. 로그인 후 공문을 열어 주세요.`, "ok"); await refreshPages(); }
    catch (e) { toast(e.message, "err", 7000); } finally { hud(false); }
  });
  const refreshPages = async () => {
    const pages = await api("browser_pages");
    $("#br-pages").innerHTML = `<option value="">가장 최근에 연 페이지</option>` + pages.map((p) => `<option value="${p.index}">${esc(p.title || p.url).slice(0, 80)}</option>`).join("");
  };
  $("#br-refresh").addEventListener("click", refreshPages);
  $("#br-pages").addEventListener("focus", refreshPages);
  $("#br-capture").addEventListener("click", () => { const v = $("#br-pages").value; doCollect("capture_browser", [v === "" ? null : Number(v), title(), useAI()]); });
  $("#url-collect").addEventListener("click", () => doCollect("collect_url", [$("#url-input").value, title(), useAI()]));
  setupDrop($("#drop-notice"), (paths) => { state.pendingFiles.push(...paths); renderPendingFiles(); });
  $("#pick-notice-files").addEventListener("click", async () => { state.pendingFiles.push(...(await pickFiles(true))); renderPendingFiles(); });
  $("#notice-files").addEventListener("click", (e) => {
    const rm = e.target.closest("[data-rm]"), mn = e.target.closest("[data-main]");
    if (rm) state.pendingFiles.splice(Number(rm.dataset.rm), 1);
    if (mn) { const [x] = state.pendingFiles.splice(Number(mn.dataset.main), 1); state.pendingFiles.unshift(x); }
    renderPendingFiles();
  });
  $("#file-collect").addEventListener("click", async () => { const paths = state.pendingFiles.slice(); state.pendingFiles = []; renderPendingFiles(); await doCollect("collect_files", [paths, title(), 0, useAI()]); });
  $("#open-root").addEventListener("click", async () => { const s = await api("get_settings"); if (!(await api("open_path", s._download_root))) toast("아직 폴더가 없습니다. 공문을 먼저 수집하세요.", "info"); });

  // 시트
  $("#nd-close").addEventListener("click", closeSheet);
  $("#sheet").addEventListener("click", (e) => { if (e.target.id === "sheet") closeSheet(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });
  $("#nd-folder").addEventListener("click", () => currentNotice && api("open_notice_folder", currentNotice.id));
  $("#nd-mail").addEventListener("click", async () => { if (!currentNotice) return; const id = currentNotice.id; closeSheet(); go("mail"); await loadMail(); $("#mc-notice").value = String(id); makeMail(); });
  $("#nd-reanalyze").addEventListener("click", async () => {
    if (!currentNotice) return;
    hud("다시 분석하는 중…");
    try { await runJob("reanalyze", [currentNotice.id], (st) => st.message && hud(st.message)); hud(false); toast("다시 분석했습니다", "ok"); openNotice(currentNotice.id); loadNotices(); }
    catch (e) { hud(false); toast(e.message, "err"); }
  });
  $("#nd-delete").addEventListener("click", async () => {
    if (!currentNotice) return;
    if (!confirm("이 공문을 목록에서 삭제할까요? (연결된 할 일도 삭제됩니다)")) return;
    const delFolder = confirm("다운로드 폴더의 파일도 함께 삭제할까요?\n[확인] 파일까지 삭제 / [취소] 목록에서만 삭제");
    await api("delete_notice", currentNotice.id, delFolder);
    closeSheet(); toast("삭제했습니다", "ok"); loadNotices(); loadHome();
  });

  // 할 일
  segmented($("#task-filter"), loadTasks);
  $("#task-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("add_task", $("#task-title").value, $("#task-due").value, ""); $("#task-title").value = ""; $("#task-due").value = ""; loadTasks(); }
    catch (er) { toast(er.message, "err"); }
  });
  $("#task-list").addEventListener("change", async (e) => {
    if (!e.target.classList.contains("task-check")) return;
    const id = Number(e.target.closest("li").dataset.id);
    await api("update_task", id, { done: e.target.checked });
    setTimeout(loadTasks, 250);
  });
  $("#task-list").addEventListener("click", async (e) => {
    const del = e.target.closest("[data-del]"), ed = e.target.closest("[data-edit]");
    if (del && confirm("할 일을 삭제할까요?")) { await api("delete_task", Number(del.dataset.del)); loadTasks(); }
    if (ed) {
      const t = state.tasks.find((x) => x.id === Number(ed.dataset.edit));
      const v = prompt("기한 (YYYY-MM-DD, 비우면 기한 없음)", t?.due || "");
      if (v === null) return;
      if (v && !/^\d{4}-\d{2}-\d{2}$/.test(v)) return toast("날짜 형식은 YYYY-MM-DD 입니다", "err");
      await api("update_task", t.id, { due: v }); loadTasks();
    }
  });
  $("#cal").addEventListener("click", (e) => { const d = e.target.closest(".day"); if (d) { state.calSel = d.dataset.date; renderCalendar(); } });
  $("#cal-prev").addEventListener("click", () => { state.calMonth = new Date(state.calMonth.getFullYear(), state.calMonth.getMonth() - 1, 1); renderCalendar(); });
  $("#cal-next").addEventListener("click", () => { state.calMonth = new Date(state.calMonth.getFullYear(), state.calMonth.getMonth() + 1, 1); renderCalendar(); });
  $("#export-ics").addEventListener("click", async () => { const p = await api("export_ics"); toast(`일정 파일을 저장했습니다: ${baseName(p)} (Outlook 등에서 열기)`, "ok", 6000); api("open_path", p.replace(/[\\/][^\\/]+$/, "")); });

  // 메일
  segmented($("#mail-mode"), (v) => $$(".mail-pane").forEach((p) => p.classList.toggle("on", p.dataset.mode === v)));
  $("#mc-make").addEventListener("click", () => makeMail().catch((e) => toast(e.message, "err")));
  $("#mc-copy").addEventListener("click", async () => { await copyText(`제목: ${$("#mc-subject").value}\n\n${$("#mc-body").value}`); toast("메일 내용을 복사했습니다", "ok"); });
  $("#mc-mailto").addEventListener("click", () => {
    const href = `mailto:?subject=${encodeURIComponent($("#mc-subject").value)}&body=${encodeURIComponent($("#mc-body").value)}`;
    if (href.length > 1900) { copyText($("#mc-body").value); toast("본문이 길어 제목만 전달합니다. 본문은 복사되었으니 붙여넣기 하세요.", "info", 6000); location.href = `mailto:?subject=${encodeURIComponent($("#mc-subject").value)}`; }
    else location.href = href;
  });
  $("#mc-save").addEventListener("click", async () => { const nid = $("#mc-notice").value; const p = await api("save_mail_draft", $("#mc-subject").value, $("#mc-body").value, nid ? Number(nid) : null); toast(`저장했습니다: ${p}`, "ok", 6000); });
  $("#mc-polish").addEventListener("click", async () => {
    const body = $("#mc-body").value;
    if (!body.trim()) return toast("먼저 메일 초안을 만들어 주세요", "info");
    const btn = $("#mc-polish"); btn.disabled = true;
    try { const r = await runJob("polish_mail", [body], (st) => { if (st.text) $("#mc-body").value = st.text; }); $("#mc-body").value = r.body; toast("AI가 문장을 다듬었습니다. 내용을 확인해 주세요.", "ok"); }
    catch (e) { $("#mc-body").value = body; toast(e.message, "err"); } finally { btn.disabled = false; }
  });
  $("#tpl-list").addEventListener("click", (e) => { const li = e.target.closest("[data-tpl]"); if (li) { state.tplSel = Number(li.dataset.tpl); renderTplList(); } });
  $("#tpl-new").addEventListener("click", () => { state.tplSel = null; renderTplList(); $("#tpl-name").focus(); });
  $("#tpl-vars").addEventListener("click", (e) => {
    const c = e.target.closest("[data-var]"); if (!c) return;
    const active = document.activeElement === $("#tpl-subject") ? $("#tpl-subject") : $("#tpl-body");
    const ins = `{{${c.dataset.var}}}`, s = active.selectionStart ?? active.value.length;
    active.value = active.value.slice(0, s) + ins + active.value.slice(active.selectionEnd ?? s);
    active.focus(); active.selectionStart = active.selectionEnd = s + ins.length;
  });
  $("#tpl-vars").addEventListener("mousedown", (e) => e.preventDefault());
  $("#tpl-save").addEventListener("click", async () => {
    try { state.tplSel = await api("save_template", $("#tpl-name").value, $("#tpl-subject").value, $("#tpl-body").value, state.tplSel); toast("양식을 저장했습니다", "ok"); loadMail(); }
    catch (e) { toast(e.message, "err"); }
  });
  $("#tpl-delete").addEventListener("click", async () => { if (state.tplSel && confirm("이 양식을 삭제할까요?")) { await api("delete_template", state.tplSel); state.tplSel = null; loadMail(); } });

  // 저장소
  $("#lib-reindex").addEventListener("click", () => reindex(false));
  $("#lib-reindex-force").addEventListener("click", () => reindex(true));
  $("#lib-dir-add").addEventListener("click", async () => { try { await api("add_regulation_dir", $("#lib-dir-input").value.trim()); $("#lib-dir-input").value = ""; loadLibrary(); toast("폴더를 추가했습니다. '색인 갱신'을 눌러 주세요.", "ok"); } catch (e) { toast(e.message, "err"); } });
  $("#lib-dir-pick").addEventListener("click", async () => { if (!state.info.native) return toast("브라우저 모드에서는 경로를 직접 입력해 주세요", "info"); const p = await api("pick_folder"); if (p) $("#lib-dir-input").value = p; });
  $("#lib-dirs").addEventListener("click", async (e) => { const b = e.target.closest("[data-rmdir]"); if (b && confirm("저장소 목록에서 제거할까요? (파일은 삭제되지 않습니다)")) { await api("remove_regulation_dir", b.dataset.rmdir); reindex(false); } });
  setupDrop($("#drop-lib"), importLibFiles);
  $("#lib-pick-files").addEventListener("click", async () => importLibFiles(await pickFiles(true)));

  // 설정
  segmented($("#set-theme"), applyTheme);
  $("#set-save").addEventListener("click", saveSettings);
  $("#set-ai-check").addEventListener("click", () => { refreshAI(); loadModels(); });
  $("#model-grid").addEventListener("click", async (e) => {
    const u = e.target.closest("[data-use]"), p = e.target.closest("[data-pull]"), d = e.target.closest("[data-mdel]"), g = e.target.closest("[data-gguf]");
    if (u) { await api("use_model", u.dataset.use); toast(`${u.dataset.use} 모델을 사용합니다`, "ok"); loadModels(); refreshAI(); }
    if (p) modelJob("pull_model", [p.dataset.pull], `${p.dataset.pull} 모델을 받았습니다. '사용'을 눌러 적용하세요.`);
    if (d && confirm(`${d.dataset.mdel} 모델을 PC에서 삭제할까요? (다시 받을 수 있습니다)`)) {
      try { await api("delete_model", d.dataset.mdel); toast("삭제했습니다", "ok"); } catch (er) { toast(er.message, "err"); }
      loadModels(); refreshAI();
    }
    if (g) {
      ggufTarget = g.dataset.gguf;
      const m = (await api("model_catalog")).models.find((x) => x.id === ggufTarget);
      $("#gguf-title").textContent = `${m.name} 등록`;
      $("#gguf-hf").dataset.href = m.hf || "https://huggingface.co";
      $("#gguf-box").classList.remove("hidden");
      $("#gguf-path").focus();
    }
  });
  $("#gguf-hf").addEventListener("click", (e) => { e.preventDefault(); window.open(e.target.dataset.href, "_blank"); });
  $("#gguf-pick").addEventListener("click", async () => {
    if (!state.info.native) return toast("브라우저 모드에서는 파일 경로를 직접 입력해 주세요", "info");
    const p = await api("pick_files", false); if (p && p[0]) $("#gguf-path").value = p[0];
  });
  $("#gguf-go").addEventListener("click", () => {
    const v = $("#gguf-path").value.trim();
    if (!v || !ggufTarget) return toast("GGUF 파일 경로를 입력하세요", "info");
    if (/^hf\.co\//i.test(v)) return modelJob("pull_model", [v, ggufTarget], `${ggufTarget} 모델을 받았습니다. '사용'을 눌러 적용하세요.`);
    modelJob("import_gguf", [v, ggufTarget], `${ggufTarget} 모델을 등록했습니다. '사용'을 눌러 적용하세요.`);
  });
  $("#set-root-pick").addEventListener("click", async () => { if (!state.info.native) return toast("브라우저 모드에서는 경로를 직접 입력해 주세요", "info"); const p = await api("pick_folder"); if (p) $("#set-download_root").value = p; });
}

// ------------------------------------------------------------------ 시작
(async function init() {
  paintIcons();
  bind();
  try {
    [state.info, state.settings] = await Promise.all([api("app_info"), api("get_settings")]);
    applyTheme(state.settings.theme);
    await loadHome();
    loadNotices();
    refreshAI();
    setInterval(refreshAI, 60000);
  } catch (e) { toast("초기화 실패: " + e.message, "err", 10000); }
})();
