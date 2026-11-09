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
  let r;
  // 내부 서버가 잠깐 바쁘거나 연결을 거절하면(Failed to fetch) 조금 기다렸다 다시 시도한다
  for (let i = 0; ; i++) {
    try {
      r = await fetch("/api/" + name, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Seomu-Token": window.SEOMU_TOKEN || "" },
        body: JSON.stringify({ args }),
      });
      break;
    } catch (e) {
      if (i >= 3) throw new Error("프로그램 내부 연결이 끊겼습니다. 창을 닫고 run.bat으로 다시 실행해 주세요. 계속되면 설정 맨 아래 '데이터 폴더'의 seomu.log 파일을 보내 주세요.");
      await sleep(300 * (i + 1));
    }
  }
  if (r.status === 403) {
    // 프로그램 내부 서버가 다시 시작돼 보안 토큰이 바뀌었다 → 화면을 새로 불러 새 토큰을 받는다 (한 번만)
    if (!sessionStorage.getItem("seomu_reloaded")) {
      try { sessionStorage.setItem("seomu_reloaded", "1"); } catch { /* 저장 불가해도 새로고침 */ }
      location.reload();
    }
    throw new Error("프로그램이 다시 시작되었습니다. 창을 닫고 run.bat으로 다시 실행해 주세요.");
  }
  try { sessionStorage.removeItem("seomu_reloaded"); } catch { /* 무시 */ }
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
  if (text === false) {
    $("#hud-action").classList.add("hidden"); $("#hud-files").classList.add("hidden");
    return $("#hud").classList.add("hidden");
  }
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
  const loaders = { home: loadHome, ask: loadChat, guide: loadGuide, collect: loadNotices, tasks: loadTasks, mail: loadMail, report: loadReport, library: loadLibrary, settings: loadSettings };
  return loaders[page] ? loaders[page]() : Promise.resolve();
}

// ------------------------------------------------------------------ 상황 안내 (서무비서)
let guideCur = null, orgForms = [];
async function loadForms() {
  try {
    const r = await api("list_forms");
    orgForms = r.forms || [];
    $("#form-list").innerHTML = orgForms.length ? orgForms.map((f) => `<li>
      <div class="t">${esc(f.name)} <span class="badge">${esc(f.ext.toUpperCase())}</span></div>
      <div class="muted small row tight"><span>${f.fields.length ? `채울 칸: ${esc(f.fields.slice(0, 5).join(", "))}${f.fields.length > 5 ? " 등" : ""}` : "채울 칸을 찾지 못함"}</span>
        <span class="spacer"></span><button class="btn ghost sm" data-open="${esc(f.path)}">열기</button>
        <button class="btn ghost sm danger" data-fdel="${esc(f.name)}" title="서식 삭제">${svg("trash")}</button></div></li>`).join("")
      : `<li class="muted small">올린 기관 서식이 없습니다.</li>`;
  } catch (e) { $("#form-list").innerHTML = `<li class="muted small">${esc(e.message)}</li>`; }
}
async function addForms(paths) {
  if (!paths || !paths.length) return;
  try {
    const r = await api("add_forms", paths);
    toast(`기관 서식 ${r.added.length}개를 올렸습니다`, "ok");
    await loadForms();
    if (guideCur) renderGuide(guideCur);
  } catch (e) { toast(e.message, "err", 8000); }
}
async function loadGuide() {
  loadForms();
  try {
    const h = await api("guide_history");
    $("#guide-hist").innerHTML = h.length ? h.map((g) => `<li data-gid="${g.id}" class="${guideCur && guideCur.id === g.id ? "on" : ""}">
      <div class="t">${esc(g.situation)}</div>
      <div class="muted small row tight">${g.kind ? `<span class="badge">${esc(g.kind)}</span>` : ""}<span>${esc(relTime(g.created_at))}</span>
        <span class="spacer"></span><button class="btn ghost sm danger" data-gdel="${g.id}" title="삭제">${svg("trash")}</button></div></li>`).join("")
      : `<li class="muted small">아직 받은 안내가 없습니다.</li>`;
  } catch (e) { $("#guide-hist").innerHTML = `<li class="muted small">${esc(e.message)}</li>`; }
}
async function askGuide(text) {
  text = (text || $("#guide-input").value).trim();
  if (!text) return toast("상황을 입력하세요", "info");
  $("#guide-input").value = text;
  const btn = $("#guide-go");
  btn.disabled = true;
  $("#guide-result").innerHTML = `<div class="card muted" id="guide-wait">관련 규정을 찾는 중…</div>`;
  try {
    const r = await runJob("guide", [text, $("#guide-ai").checked], (st) => {
      const w = $("#guide-wait");
      if (w) w.textContent = st.message || "안내를 만드는 중…";
    });
    guideCur = r;
    renderGuide(r);
    loadGuide();
  } catch (e) {
    $("#guide-result").innerHTML = `<div class="card muted">${esc(e.message)}</div>`;
    toast(e.message, "err");
  } finally { btn.disabled = false; }
}
function guideDate(sit) {
  if (!sit.start) return "";
  return sit.end && sit.end !== sit.start ? `${fmtDate(sit.start)} ~ ${fmtDate(sit.end)}` : fmtDate(sit.start);
}
function renderGuide(r) {
  const sit = r.situation || {};
  const facts = [["업무", sit.kind || "일반"], ["날짜", guideDate(sit)], ["장소", sit.place], ["목적", sit.purpose],
    ["품목", sit.item], ["금액", sit.amount ? sit.amount.toLocaleString() + "원" : ""]]
    .filter((f) => f[1]).map((f) => `<span class="badge">${esc(f[0])}: ${esc(f[1])}</span>`).join(" ");
  const steps = (r.steps || []).map((st, i) => `
    <li class="${st.skip ? "skip" : ""}">
      <div class="num">${i + 1}</div>
      <div class="body"><div class="t">${esc(st.title)}</div>
        <div class="muted small">${esc(st.basis)}${st.due_text ? ` · 규정: ${esc(st.due_text)}` : ""}</div>
        ${st.skip ? `<div class="small skip-note">${esc(st.skip)}</div>` : ""}</div>
      <div class="due">${st.due ? `<b>${esc(fmtDate(st.due))}</b>${st.late ? '<span class="badge red">기한 지남</span>' : ""}` : ""}</div>
    </li>`).join("");
  const checks = (r.checks || []).map((c) => `<li>${esc(c.text)} <span class="muted small">— ${esc(c.basis)}</span></li>`).join("");
  const forms = (r.forms || []).map((f, i) => `
    <div class="guide-draft">
      <div class="row tight wrap"><b>${esc(f.name)}</b>${f.blanks ? `<span class="badge orange">채울 칸 ${f.blanks}곳(○○)</span>` : ""}<span class="spacer"></span>
        <button class="btn sm" data-fcopy="${i}">${svg("copy")} 복사</button>
        <button class="btn sm" data-fsave="${i}" data-fmt="txt">${svg("download")} txt 저장</button>
        <button class="btn sm" data-fsave="${i}" data-fmt="hwpx">${svg("doc")} 한글(hwpx) 저장</button></div>
      ${orgForms.length ? `<div class="row tight wrap org-form-row"><span class="muted small">기관 서식</span>
        <select class="input sm" data-ftpl="${i}"><option value="">고르세요</option>${orgForms.map((o) =>
          `<option ${o.name === f.template ? "selected" : ""}>${esc(o.name)}</option>`).join("")}</select>
        <button class="btn primary sm" data-ffill="${i}">${svg("doc")} 기관 서식으로 작성</button>
        ${f.template ? '<span class="badge green">이름이 맞는 서식을 골라 두었습니다</span>' : ""}</div>` : ""}
      <textarea class="input mono" rows="${Math.min(24, f.body.split("\n").length + 1)}" data-fbody="${i}">${esc(f.body)}</textarea>
    </div>`).join("");
  const tasks = (r.tasks || []).map((t, i) => `
    <label class="guide-task"><input type="checkbox" data-tk="${i}" checked>
      <span class="t">${esc(t.title)}</span><span class="spacer"></span>${t.due ? `<span class="badge blue">${esc(fmtDate(t.due))}</span>` : '<span class="badge">기한 없음</span>'}</label>`).join("");
  const src = (r.sources || []).map((h) => `<li><b>「${esc(h.title)}」 ${esc(h.heading || "")}</b>
    <div class="muted small">${esc((h.text || "").slice(0, 260))}${(h.text || "").length > 260 ? "…" : ""}</div></li>`).join("");
  $("#guide-result").innerHTML = `
    <div class="card">
      <div class="card-head"><h3>상황 정리</h3><span class="muted small">${r.mode === "llm" ? `로컬 AI 보완 · ${esc(r.model || "")}` : "규칙 기반"}</span></div>
      <p class="guide-summary">${esc(r.summary)}</p>
      <div class="row wrap tight">${facts}</div>
      ${r.notice ? `<div class="engine-notice warn-notice" style="margin-top:10px">${esc(r.notice)}</div>` : ""}
      ${(r.tips || []).length ? `<ul class="guide-tips">${r.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    </div>
    <div class="card">
      <div class="card-head"><h3>① 절차 확인</h3><span class="muted small">규정의 의무 조항 · 기한은 상황 날짜로 계산</span></div>
      ${steps ? `<ol class="guide-steps">${steps}</ol>` : `<div class="muted small">규정에서 이 상황의 절차 조항을 찾지 못했습니다. 규정 저장소에 해당 규정·지침을 추가해 보세요.</div>`}
      ${checks ? `<div class="guide-sub">확인할 제한·기준</div><ul class="guide-checks">${checks}</ul>` : ""}
      ${(r.prep || []).length ? `<div class="guide-sub">준비·첨부 서류</div><div class="row wrap tight">${r.prep.map((p) => `<span class="badge green">${esc(p)}</span>`).join(" ")}</div>` : ""}
    </div>
    <div class="card">
      <div class="card-head"><h3>② 서식 초안</h3><span class="muted small">○○ 칸을 채워 쓰세요 · 고친 내용 그대로 복사·저장</span></div>
      ${forms || '<div class="muted small">만들 서식이 없습니다.</div>'}
    </div>
    <div class="card">
      <div class="card-head"><h3>③ 다음 할 일</h3><button class="btn primary sm" id="guide-addtasks">${svg("plus")} 선택한 일을 할 일로 등록</button></div>
      ${tasks || '<div class="muted small">등록할 할 일이 없습니다.</div>'}
    </div>
    ${src ? `<div class="card"><div class="card-head"><h3>근거 조문</h3></div><ul class="guide-src">${src}</ul></div>` : ""}`;
}
function bindForms() {
  $("#form-add").addEventListener("click", async () => {
    if (!state.info.native) return toast("브라우저 모드에서는 서식 파일을 끌어다 놓아 주세요", "info");
    addForms(await pickFiles(true));
  });
  setupDrop($("#drop-forms"), addForms);
  $("#form-list").addEventListener("click", async (e) => {
    const d = e.target.closest("[data-fdel]");
    if (!d || !confirm(`'${d.dataset.fdel}' 서식을 지울까요? (처음 올린 원본 파일은 그대로 있습니다)`)) return;
    try { await api("delete_form", d.dataset.fdel); } catch (er) { toast(er.message, "err"); }
    await loadForms();
    if (guideCur) renderGuide(guideCur);
  });
}
function bindGuide() {
  bindForms();
  $("#guide-form").addEventListener("submit", (e) => { e.preventDefault(); askGuide(); });
  $("#guide-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); askGuide(); }
  });
  $("#guide-suggest").addEventListener("click", (e) => { const c = e.target.closest(".chip"); if (c) askGuide(c.textContent); });
  $("#guide-hist").addEventListener("click", async (e) => {
    const del = e.target.closest("[data-gdel]");
    if (del) {
      e.stopPropagation();
      const id = Number(del.dataset.gdel);
      try { await api("delete_guide", id); } catch (er) { return toast(er.message, "err"); }
      if (guideCur && guideCur.id === id) { guideCur = null; $("#guide-result").innerHTML = ""; }
      return loadGuide();
    }
    const li = e.target.closest("[data-gid]");
    if (!li) return;
    try {
      const g = await api("get_guide", Number(li.dataset.gid));
      if (g) { guideCur = g; $("#guide-input").value = (g.situation || {}).text || ""; renderGuide(g); loadGuide(); }
    } catch (er) { toast(er.message, "err"); }
  });
  $("#guide-result").addEventListener("click", async (e) => {
    const cp = e.target.closest("[data-fcopy]"), sv = e.target.closest("[data-fsave]"), fl = e.target.closest("[data-ffill]");
    if (fl) {
      const i = fl.dataset.ffill, tpl = $(`[data-ftpl="${i}"]`).value;
      if (!tpl) return toast("채울 기관 서식을 고르세요", "info");
      try {
        const r = await api("fill_guide_form", guideCur.id, Number(i), $(`[data-fbody="${i}"]`).value, tpl);
        toast(`'${r.template}' 서식에 ${r.filled.length}칸을 채웠습니다` + (r.missing.length ? ` · 비워 둔 칸: ${r.missing.slice(0, 4).join(", ")}` : ""), "ok", 7000);
        openPath(r.folder);
      } catch (er) { toast(er.message, "err", 8000); }
      return;
    }
    if (cp) { await copyText($(`[data-fbody="${cp.dataset.fcopy}"]`).value); return toast("초안을 복사했습니다", "ok"); }
    if (sv) {
      const f = guideCur.forms[Number(sv.dataset.fsave)];
      try {
        const r = await api("save_guide_form", f.name, $(`[data-fbody="${sv.dataset.fsave}"]`).value, sv.dataset.fmt);
        toast(`저장했습니다: ${baseName(r.path)}`, "ok", 5000);
        openPath(r.folder);
      } catch (er) { toast(er.message, "err"); }
      return;
    }
    if (e.target.closest("#guide-addtasks")) {
      const picked = $$("[data-tk]").filter((c) => c.checked).map((c) => guideCur.tasks[Number(c.dataset.tk)]);
      if (!picked.length) return toast("등록할 일을 고르세요", "info");
      try {
        const r = await api("guide_add_tasks", picked);
        toast(r.added ? `할 일 ${r.added}개를 등록했습니다` : "이미 등록된 할 일입니다", r.added ? "ok" : "info");
        loadTasks().catch(() => {});          // 할 일 목록·메뉴 배지 갱신
      } catch (er) { toast(er.message, "err"); }
    }
  });
}

// ------------------------------------------------------------------ AI 상태
async function refreshAI() {
  const chip = $("#ai-chip");
  try {
    const st = await api("llm_status");
    chip.classList.toggle("ok", st.ok && !!st.chat_model);
    chip.classList.toggle("bad", !(st.ok && st.chat_model));
    $(".ai-chip-text", chip).textContent = st.ok && st.chat_model
      ? `${st.engine === "builtin" ? "내장 AI" : "로컬 AI"} · ${st.chat_model}`
      : st.need_engine
        ? ((st.engine_install || {}).state === "running" ? "AI 엔진 받는 중… (검색 모드)" : "AI 엔진 파일 없음 (검색 모드)")
        : (st.engine === "builtin" ? "모델 파일 없음 (검색 모드)" : "AI 엔진 미연결 (검색 모드)");
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
    <li class="clickable" data-goto="tasks"><div class="main-col"><div class="t">${esc(taskTitle(t))}</div>
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
    ${a.ai_status === "running" ? '<span class="badge purple">AI 분석 중</span>' : ""}
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
  state.notices.filter((n) => (n.analysis || {}).ai_status === "running").forEach((n) => watchAI(n.id));
  $("#notice-list").innerHTML = state.notices.length ? state.notices.map(noticeRow).join("")
    : `<li class="empty">아직 수집한 공문이 없습니다. 위에서 공문을 수집해 보세요.</li>`;
  if ($("#collect-mode button.on")?.dataset.v === "window") loadWindows();
  $("#br-hint").textContent = state.info.browser_available ? "" : "※ 브라우저 연동을 쓰려면 Playwright 설치가 필요합니다 (README 참고). 주소 수집과 파일 가져오기는 바로 쓸 수 있습니다.";
}
async function doCollect(name, args) {
  hud("공문을 수집하는 중…");
  try {
    const notice = await runJob(name, args, (st) => {
      if (st.message) hud(st.message);
      let info = null;
      try { info = st.text ? JSON.parse(st.text) : null; } catch { info = null; }
      if (info && info.phase === "watch") {
        const act = $("#hud-action");
        if (act.classList.contains("hidden")) {
          act.classList.remove("hidden");
          act.textContent = "붙임 수집 완료"; act.disabled = false;
          act.onclick = () => { api("job_signal", st.id, "done"); act.textContent = "정리하는 중…"; act.disabled = true; };
        }
        const box = $("#hud-files");
        box.classList.remove("hidden");
        const body = info.has_text ? "✅ " + esc(info.how) : "⏳ 읽지 못함 — 그 창에서 본문을 복사(Ctrl+A, Ctrl+C 또는 [본문복사])해 주세요";
        const exp = info.expected || [];
        const files = exp.length
          ? exp.map((e) => "<div>" + (e.file ? "✅ " : "⏳ ") + esc(e.name) + (e.file ? ' <span style="opacity:.6">← ' + esc(e.file) + "</span>" : "") + "</div>").join("") +
            info.files.filter((f) => !exp.some((e) => e.file === f)).map((f) => "<div>📎 " + esc(f) + "</div>").join("")
          : (info.files.length ? info.files.map((f) => "<div>📎 " + esc(f) + "</div>").join("") : "<div>📎 붙임 표기가 없거나 대기 중…</div>");
        const listed = info.listed && info.listed.length ? '<div style="opacity:.7">창의 붙임목록: ' + esc(info.listed.join(", ")) + "</div>" : "";
        box.innerHTML = "<div>본문: " + body + "</div>" + files + listed;
      }
    });
    hud(false);
    const a = notice.analysis || {};
    const stale = new Date(Date.now() - 14 * 86400000).toISOString().slice(0, 10);
    const live = (a.deadlines || []).filter((d) => d.date >= stale).length, old = (a.deadlines || []).length - live;
    if (notice.duplicate) {
      toast(`이미 수집한 공문입니다: ${a.folder_name || notice.title} · ` +
        (notice.added_files ? `새 붙임 ${notice.added_files}개를 더했습니다` : "새로 더할 붙임이 없습니다") + " (할 일은 그대로)", "info", 5000);
    } else {
      toast(`정리 완료: ${a.folder_name || notice.title} · 할 일 ${live}건 등록` + (old ? ` (이미 지난 기한 ${old}건은 상세에만 표시)` : "") +
        (a.ai_status === "running" ? " · 로컬 AI가 이어서 자세히 분석합니다" : ""), "ok", 5000);
    }
    if (a.ai_status === "running") watchAI(notice.id);
    await loadNotices();
    await openNotice(notice.id);
    const need = notice.need_upload || [];
    if (need.length || notice.maybe_attach) openUpload(notice.id, need, notice.maybe_attach);
  } catch (e) { hud(false); toast(e.message, "err", 6000); }
}
function renderPendingFiles() {
  const ul = $("#notice-files");
  ul.innerHTML = state.pendingFiles.map((p, i) => `<li>${i === 0 ? '<span class="tag">본문</span>' : '<span class="tag" style="color:var(--text-2)">붙임</span>'}
    <span>${esc(baseName(p))}</span><span class="spacer"></span>
    ${i ? `<button class="btn ghost sm" data-main="${i}">본문으로</button>` : ""}<button class="btn ghost sm" data-rm="${i}">${svg("close")}</button></li>`).join("");
  $("#file-collect").disabled = !state.pendingFiles.length;
}

// 열린 창 목록
let winSel = null, winAll = [];
const NOTICE_WORDS = /(알림|요청|협조|안내|제출|회신|통보|개최|계획|시행|공문|문서|조사|의뢰)/;
async function loadWindows() {
  try { const s = await api("get_settings"); $("#win-foreground").checked = !!s.capture_foreground; } catch { /* 설정 읽기 실패는 무시 */ }
  if (!state.info.windows_available) {
    $("#win-list").innerHTML = '<li class="empty">열린 창 수집은 Windows에서 사용할 수 있습니다.</li>';
    return;
  }
  try { winAll = await api("list_windows"); } catch (e) { toast(e.message, "err"); winAll = []; }
  renderWindows();
  $("#win-hint").textContent = state.info.uia_available ? "" : "※ uiautomation 패키지가 없어 화면 글자 정보 읽기와 일부 버튼 누르기는 생략됩니다 (본문복사 버튼·전체 선택·복사·OCR·파일 감시는 동작). 설치: .venv\\Scripts\\pip install uiautomation";
}
function renderWindows() {
  const q = $("#win-filter").value.trim();
  const list = winAll.filter((w) => !q || w.title.includes(q) || (w.process || "").toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (NOTICE_WORDS.test(b.title) ? 1 : 0) - (NOTICE_WORDS.test(a.title) ? 1 : 0));
  $("#win-list").innerHTML = list.length ? list.map((w) => `
    <li class="${w.hwnd === winSel ? "on" : ""} ${NOTICE_WORDS.test(w.title) ? "likely" : ""}" data-hwnd="${w.hwnd}">
      <div class="ico">${svg(/edge|chrome|whale|firefox/i.test(w.process) ? "globe" : "doc")}</div>
      <div class="main-col"><div class="t">${esc(w.title)}</div><div class="s">${esc(w.process || w.cls)}</div></div></li>`).join("")
    : `<li class="empty">${q ? "검색 결과가 없습니다" : "열린 창이 없습니다. 공문을 띄운 뒤 새로고침하세요."}</li>`;
  $("#win-capture").disabled = !list.some((w) => w.hwnd === winSel);
}

// 공문 상세 시트
let currentNotice = null;
async function openNotice(id) {
  const n = await api("get_notice", id);
  if (!n) return;
  currentNotice = n;
  const a = n.analysis || {};
  $("#nd-title").textContent = a.folder_name || n.title;
  const how = a.ai_status === "running" ? "규칙 기반 분석 · 로컬 AI가 보완 분석 중…"
    : a.mode === "llm" ? `로컬 AI 분석 (${a.model || ""}${a.ai_seconds ? ", " + a.ai_seconds + "초" : ""})` : "규칙 기반 분석";
  $("#nd-date").textContent = `${n.created_at.replace("T", " ").slice(0, 16)} 수집 · ${how}`;
  const today = new Date(new Date().toDateString());
  const dls = (a.deadlines || []).map((d) => {
    const dt = new Date(d.date + "T00:00:00");
    const dd = Math.round((dt - today) / 86400000);
    return `<div class="deadline"><div class="date"><div class="m">${dt.getMonth() + 1}월</div><div class="d">${dt.getDate()}</div></div>
      <div class="what"><div>${esc(d.what)}</div><div class="muted small">${fmtDate(d.date)} ${esc(d.time || "")} · ${d.source === "AI" ? "AI 분석" : "본문에서 찾음"}</div></div>${dd < -14 ? '<span class="badge">지난 기한</span>' : ddayBadge(dd)}</div>`;
  }).join("") || `<div class="muted">본문에서 제출 기한을 찾지 못했습니다.</div>`;
  const subs = (a.submissions || []).map((s) => `<li><div>${esc(s.item)}${s.how || s.to ? `<div class="muted small">${esc([s.how, s.to].filter(Boolean).join(" · "))}</div>` : ""}</div></li>`).join("");
  const acts = (a.actions || []).map((x) => `<li>${esc(x)}</li>`).join("");
  const ev = a.event || {};
  const evRows = [["행사명", ev.name], ["일시", ev.date], ["장소", ev.place]].filter((r) => r[1]);
  // 붙임: 누르면 앱 안에서 내용 미리보기 (한글·PDF 뷰어가 없는 PC에서도 확인), [열기]는 PC 프로그램으로
  const files = (n.attachments || []).map((f) => `<div class="attach" ${f.ok ? `data-preview="${esc(f.path)}"` : ""}>
      <div class="ext ${extOf(f.name)}">${esc(extOf(f.name)).slice(0, 4)}</div>
      <div class="main-col"><div>${esc(f.name)}</div><div class="muted small">${f.ok ? (f.from === "직접 넣은 파일" ? "직접 넣은 파일" : "공문 폴더에 있음") + " · 눌러서 내용 보기" : "받지 못함: " + esc(f.error || "")}</div></div>
      ${f.ok ? `<div class="acts"><button class="btn ghost sm" data-open="${esc(f.path)}">열기</button></div>` : ""}</div>`).join("")
    || `<div class="muted">붙임 파일이 없습니다.</div>`;
  // 요약: 첫 줄은 핵심, ' — ' 뒤의 설명과 다음 줄들은 한 줄씩 (긴 한 줄로 이어 붙이지 않는다)
  const sumParts = String(a.summary || "-").split("\n").flatMap((l) => l.split(/\s+—\s+/)).map((l) => l.trim()).filter(Boolean);
  const summary = `<div class="sum-head">${esc(sumParts[0] || "-")}</div>` +
    (sumParts.length > 1 ? `<ul class="sum-sub">${sumParts.slice(1).map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : "");
  $("#nd-body").innerHTML = `
    <div class="section"><h4>요약</h4><div class="summary-box">${summary}</div></div>
    <div class="section"><h4>제출 기한</h4>${dls}</div>
    <div class="grid-2">
      <div class="section"><h4>제출물</h4>${subs ? `<ul class="check-list">${subs}</ul>` : '<div class="muted">확인된 제출물 없음</div>'}</div>
      <div class="section"><h4>할 일</h4>${acts ? `<ul class="check-list">${acts}</ul>` : '<div class="muted">-</div>'}</div>
    </div>
    ${evRows.length ? `<div class="section"><h4>행사 정보</h4><dl class="kv">${evRows.map((r) => `<dt>${r[0]}</dt><dd>${esc(r[1])}</dd>`).join("")}</dl></div>` : ""}
    ${a.contact ? `<div class="section"><h4>문의처</h4><div class="contact-lines">${String(a.contact).split(/\n|\s+\/\s+/)
      .map((c) => c.trim()).filter(Boolean).map((c) => `<div>${esc(c)}</div>`).join("")}</div></div>` : ""}
    <div class="section"><h4 class="row tight">붙임 파일 · ${esc(baseName(n.folder))}<span class="spacer"></span>
      <button class="btn sm" data-upload-notice="${n.id}">${svg("download")} 붙임 올리기</button></h4>${files}</div>
    ${a.llm_error ? `<div class="section muted small">로컬 AI를 쓰지 못해 규칙 기반 분석 결과를 보여 줍니다. (원인: ${esc(a.llm_error)})</div>` : ""}
    <details class="raw"><summary>본문 원문 보기</summary><pre>${esc(n.body || "")}</pre></details>`;
  $("#sheet").classList.remove("hidden");
  if (a.ai_status === "running") watchAI(n.id);
}
function closeSheet() { $("#sheet").classList.add("hidden"); }

// 붙임 올리기 창
let uploadNotice = null;
function openUpload(id, missing, maybe) {
  uploadNotice = id;
  $("#up-why").textContent = missing && missing.length
    ? "아래 붙임은 자동으로 받지 못했습니다 (로그인이 필요한 내려받기이거나 뷰어에 저장 버튼이 없음). 그 창에서 붙임을 PC에 저장한 뒤 올려 주세요."
    : "본문에 붙임 표시가 있지만 붙임 이름을 알아내지 못했습니다. 붙임이 있으면 그 창에서 PC에 저장한 뒤 올려 주세요.";
  $("#up-missing").innerHTML = (missing || []).map((m) => `<li>${esc(m)}</li>`).join("");
  $("#up-sheet").classList.remove("hidden");
}
function closeUpload() { $("#up-sheet").classList.add("hidden"); }
async function uploadAttachments(paths) {
  if (!paths || !paths.length || !uploadNotice) return;
  try {
    const n = await api("add_notice_attachments", uploadNotice, paths);
    const left = (n.attachments || []).filter((f) => !f.ok).map((f) => f.name);
    toast(`붙임 ${n.added_files}개를 올렸습니다` + (left.length ? ` · 아직 남은 붙임: ${left.slice(0, 3).join(", ")}` : ""), "ok", 6000);
    if (left.length) $("#up-missing").innerHTML = left.map((m) => `<li>${esc(m)}</li>`).join("");
    else closeUpload();
    await openNotice(uploadNotice);
    loadNotices();
  } catch (e) { toast(e.message, "err"); }
}

// 파일 미리보기
let previewPath = "";
async function previewFile(path) {
  previewPath = path;
  $("#pv-title").textContent = baseName(path);
  $("#pv-meta").textContent = "내용을 읽는 중…";
  $("#pv-body").textContent = ""; $("#pv-body").classList.remove("err"); $("#pv-hint").textContent = "";
  $("#pv-sheet").classList.remove("hidden");
  try {
    const r = await api("preview_file", path);
    if (r.error) {
      $("#pv-meta").textContent = "미리보기";
      $("#pv-body").textContent = r.error; $("#pv-body").classList.add("err");
      $("#pv-hint").textContent = r.hint || "";
    } else {
      $("#pv-meta").textContent = `글자 ${r.chars.toLocaleString()}자${r.truncated ? " · 앞부분만 표시" : ""} · 서식 없이 글자만 보여 줍니다`;
      $("#pv-body").textContent = r.text;
    }
  } catch (e) { $("#pv-meta").textContent = "미리보기"; $("#pv-body").textContent = e.message; $("#pv-body").classList.add("err"); }
}
function closePreview() { $("#pv-sheet").classList.add("hidden"); }

// 백그라운드 AI 분석이 끝나면 화면 갱신
const aiWatching = new Set();
async function watchAI(id) {
  if (aiWatching.has(id)) return;
  aiWatching.add(id);
  try {
    for (let i = 0; i < 400; i++) {          // 최대 약 20분
      await sleep(3000);
      const n = await api("get_notice", id);
      if (!n) return;
      const st = (n.analysis || {}).ai_status;
      if (st === "running") continue;
      if (st === "done") toast(`AI 분석 완료: ${(n.analysis || {}).folder_name || n.title}`, "ok");
      else toast(`AI 분석을 하지 못해 규칙 기반 결과를 유지합니다: ${(n.analysis || {}).llm_error || ""}`, "err", 7000);
      loadNotices(); loadHome();
      if (currentNotice && currentNotice.id === id && !$("#sheet").classList.contains("hidden")) openNotice(id);
      return;
    }
  } finally { aiWatching.delete(id); }
}

// ------------------------------------------------------------------ 할 일
// 할 일 제목: 공문 이름은 아래 줄에 따로 보이므로 제목 앞의 [공문 이름]은 뺀다
function taskTitle(t) { return t.notice_id ? String(t.title || "").replace(/^\[[^\]]{1,60}\]\s*/, "") : t.title; }
async function loadTasks() {
  const filter = segValue($("#task-filter"));
  const all = await api("list_tasks", true);
  state.tasks = all;
  const list = all.filter((t) => filter === "all" ? true : filter === "done" ? t.done : !t.done);
  $("#task-list").innerHTML = list.length ? list.map((t) => `
    <li class="${t.done ? "done" : ""}" data-id="${t.id}">
      <input type="checkbox" class="task-check" ${t.done ? "checked" : ""}>
      <div class="body"><div class="title" title="${esc(t.detail || t.title)}">${esc(taskTitle(t))}</div>
        <div class="sub">${t.due ? `<span class="due ${t.dday !== null && t.dday <= 0 && !t.done ? "red" : ""}">${svg("calendar")} ${fmtDate(t.due)}</span>` : ""}
        ${t.notice_title ? `<span class="link notice-name" data-notice="${t.notice_id}" title="${esc(t.notice_title)}">${svg("doc")} ${esc(t.notice_title)}</span>` : ""}</div></div>
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
    (items.length ? items.map((t) => `<div class="item">${svg("clock")}<span><b>${esc(taskTitle(t))}</b>${t.notice_title ? `<span class="cal-notice">${esc(t.notice_title)}</span>` : ""}</span></div>`).join("") : `<div class="muted">일정 없음</div>`);
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

// ------------------------------------------------------------------ 보고서 작성
async function loadReport() {
  const [r, notices] = await Promise.all([api("report_templates"), api("list_notices")]);
  state.reportTpls = r.templates;
  const cur = $("#rp-template").value;
  $("#rp-template").innerHTML = r.templates.map((t) => `<option value="${esc(t.name)}" ${t.ok ? "" : "disabled"}>${esc(t.name)}${t.builtin ? " (기본)" : ""}${t.ok ? "" : " — 사용 불가"}</option>`).join("");
  if (cur && r.templates.some((t) => t.name === cur)) $("#rp-template").value = cur;
  else { const mine = r.templates.find((t) => t.ok && !t.builtin); if (mine) $("#rp-template").value = mine.name; }
  const curN = $("#rp-notice").value;
  $("#rp-notice").innerHTML = `<option value="">(공문 없이 추가 자료로)</option>` + notices.map((n) => `<option value="${n.id}">${esc((n.analysis || {}).folder_name || n.title)}</option>`).join("");
  if (curN) $("#rp-notice").value = curN;
  renderTplInfo();
}
function renderTplInfo() {
  const t = (state.reportTpls || []).find((x) => x.name === $("#rp-template").value);
  $("#rp-del").disabled = !t || t.builtin;
  if (!t) { $("#rp-tpl-info").textContent = ""; return; }
  if (!t.ok) { $("#rp-tpl-info").textContent = t.error; return; }
  const lv = { 0: "□", 1: "○", 2: "-", 3: "․", 9: "※" };
  $("#rp-tpl-info").textContent = `문단: ${t.levels.map((l) => lv[l]).join(" ")}${t.title_box ? " · 제목 상자" : ""}${t.summary_box ? " · 요약 상자" : ""}${t.has_table ? " · 표" : ""}` +
    (t.headings.length ? ` · 대제목 예: ${t.headings.slice(0, 3).join(", ")}` : "");
}
async function addReportTemplates(paths) {
  const hwpx = paths.filter((p) => /\.hwpx$/i.test(p));
  if (paths.some((p) => /\.hwp$/i.test(p))) toast("HWP 파일은 한글에서 '다른 이름으로 저장 → HWPX'로 저장해 넣어 주세요", "err", 6000);
  if (!hwpx.length) return;
  const r = await api("add_report_templates", hwpx);
  if (r.errors.length) toast(r.errors.join("\n"), "err", 7000); else toast("보고서 양식을 등록했습니다", "ok");
  const added = baseName(hwpx[hwpx.length - 1]).replace(/\.hwpx$/i, "");
  await loadReport();
  if (r.templates.some((t) => t.name === added && t.ok)) { $("#rp-template").value = added; renderTplInfo(); }
}
async function makeReport() {
  const tpl = $("#rp-template").value, nid = $("#rp-notice").value, material = $("#rp-material").value;
  if (!tpl) return toast("보고서 양식을 먼저 넣어 주세요", "err");
  if (!nid && !material.trim()) return toast("관련 공문을 고르거나 추가 자료를 입력해 주세요", "err");
  hud("보고서를 만드는 중…");
  try {
    const r = await runJob("make_report", [tpl, nid ? Number(nid) : null, material, $("#rp-purpose").value, $("#rp-ai").checked], (st) => hud(st.message || "보고서를 만드는 중…"));
    window.__lastReport = r; state.report = r;
    $("#rp-empty").classList.add("hidden");
    $("#rp-result").classList.remove("hidden");
    $("#rp-result").textContent = r.preview;
    $("#rp-meta").textContent = `${r.mode === "llm" ? "로컬 AI 작성" : "규칙 기반 작성"} · ${r.seconds}초 · ${baseName(r.path)}`;
    $("#rp-open").disabled = $("#rp-folder").disabled = false;
    if (r.llm_error) toast(`AI를 쓸 수 없어 공문 분석 결과로 작성했습니다 (${r.llm_error})`, "info", 6000);
    else toast("보고서를 저장했습니다", "ok");
  } catch (e) { toast(e.message, "err", 6000); }
  finally { hud(false); }
}

// ------------------------------------------------------------------ 규정 저장소
let libPoll = null;
async function loadLibrary() {
  const r = await api("list_documents");
  $("#lib-dirs").innerHTML = r.dirs.map((d) => `<li><div class="notice-icon">${svg("folder")}</div><div class="main-col"><div class="t">${esc(baseName(d) || d)}</div><div class="s">${esc(d)}</div></div>
    <button class="btn ghost sm" data-open="${esc(d)}">열기</button>${r.dirs.length > 1 ? `<button class="btn ghost sm danger" data-rmdir="${esc(d)}">${svg("trash")}</button>` : ""}</li>`).join("");
  $("#lib-count").textContent = `${r.documents.length}건`;
  const catBadge = (c) => `<span class="badge ${c === "법령" ? "purple" : c === "조례" ? "blue" : c === "내규" ? "green" : ""}">${esc(c)}</span>`;
  const cats = r.categories || [];
  $("#lib-docs").innerHTML = r.documents.length ? r.documents.map((d) => `<tr><td><b>${esc(d.title)}</b>
      <div class="muted small">${d.managed ? "화면에서 추가한 규정" : "연결한 폴더의 원본"}</div></td>
    <td><select class="input sm lib-cat" data-cat="${esc(d.path)}" title="분류 바꾸기">${(cats.includes(d.category) ? cats : [d.category, ...cats])
      .map((c) => `<option ${c === d.category ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></td>
    <td>${d.n_chunks}</td><td class="muted">${esc(d.indexed_at.replace("T", " ").slice(0, 16))}</td>
    <td class="nowrap"><button class="btn ghost sm" data-open="${esc(d.path)}">열기</button>
      <button class="btn ghost sm" data-replace="${esc(d.path)}" title="개정된 규정 파일로 바꾸기">교체</button>
      <button class="btn ghost sm danger" data-rmdoc="${esc(d.path)}" data-managed="${d.managed ? 1 : 0}" title="저장소에서 빼기">${svg("trash")}</button></td></tr>`).join("")
    : `<tr><td colspan="5" class="empty-state">아직 색인된 문서가 없습니다. 파일을 추가하고 '색인 갱신'을 누르세요.</td></tr>`;
  const ex = r.excluded || [];
  $("#lib-excluded").innerHTML = ex.length ? `<div class="guide-sub">저장소에서 뺀 규정 (원본 파일은 그대로 있음)</div>
    <ul class="list">${ex.map((x) => `<li><div class="main-col"><div class="t">${esc(x.name)}</div><div class="s">${esc(x.path)}${x.exists ? "" : " · 파일 없음"}</div></div>
      <button class="btn ghost sm" data-restore="${esc(x.path)}">다시 포함</button></li>`).join("")}</ul>` : "";
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
  const eng = c.engine || {};
  state.engine = eng.kind;
  $$("#engine-seg button").forEach((b) => b.classList.toggle("on", b.dataset.v === (eng.setting || "auto")));
  $("#engine-status").innerHTML = eng.need_engine && (eng.setting || "auto") !== "ollama"
    ? `<span style="color:var(--orange)">내장 엔진 · 실행 엔진 파일(llama-server.exe) 없음</span> · 모델 폴더: <a data-open="${esc(eng.model_dir)}">${esc(eng.model_dir)}</a>`
    : eng.kind === "builtin"
    ? `내장 엔진 사용 중 (Ollama 불필요·인터넷 불필요) · 모델 폴더: <a data-open="${esc(eng.model_dir)}">${esc(eng.model_dir)}</a>`
    : `Ollama 사용 중` + (eng.server ? "" : " · 내장 엔진 없음 — 모델 카드의 [받기]를 누르면 엔진과 모델을 함께 받아 Ollama 없이 동작합니다");
  const builtin = eng.kind === "builtin";
  // 내장 엔진을 쓰거나 Ollama가 꺼져 있으면: [받기]로 엔진+모델 파일을 자동으로 받는다
  const dlMode = builtin || !c.engine_ok;
  const hasBuiltin = !!eng.server && (eng.models || []).length > 0;
  // 모델 파일은 있는데 실행 엔진(llama-server)만 없다: 엔진만 받거나 지정하면 바로 동작
  const inst = eng.install || {};
  const engineNotice = eng.need_engine && (eng.setting || "auto") !== "ollama"
    ? `<div class="engine-notice warn-notice"><b>모델 파일은 있지만 AI 실행 엔진(llama-server.exe)이 없어 AI를 쓰지 못하고 있습니다.</b><br>
        ${inst.state === "running" ? "AI 엔진을 자동으로 받는 중입니다… 끝나면 바로 AI 분석을 씁니다." :
          `인터넷이 되면 [AI 엔진 받기](약 30MB)를, 업무망 PC라면 다른 PC에서 받은 llama.cpp 압축 파일(이름에 bin-win-cpu-x64)이나 llama-server.exe를 [엔진 파일 지정]으로 넣어 주세요.
           ${inst.state === "error" ? `<div class="small" style="color:var(--orange);margin-top:4px">자동 받기 실패: ${esc(inst.message)}</div>` : ""}`}
        <div class="row tight" style="margin-top:8px">
          <button class="btn primary sm" data-engine-dl ${inst.state === "running" ? "disabled" : ""}>${svg("download")} AI 엔진 받기</button>
          <button class="btn sm" data-engine-pick>엔진 파일 지정</button>
          <span class="muted small">넣을 폴더: <a data-open="${esc(eng.engine_dir || "")}">${esc(eng.engine_dir || "")}</a></span>
        </div></div>`
    : "";
  const notice = engineNotice || (!c.engine_ok && !builtin
    ? (hasBuiltin
      ? `<div class="engine-notice">Ollama가 실행 중이 아닙니다. 이 PC에는 내장 엔진과 모델이 이미 있으니 위에서 <b>[자동]</b> 또는 <b>[내장 엔진]</b>을 고르면 바로 쓸 수 있습니다.</div>`
      : `<div class="engine-notice">Ollama가 실행 중이 아닙니다. 쓰실 모델의 <b>[받기]</b>를 누르면 Ollama 없이 동작하는 내장 엔진과 모델을 자동으로 받습니다.</div>`) : "");
  state.catalog = c.models;
  $("#model-grid").innerHTML = notice + c.models.map((m) => {
    const installed = dlMode ? (builtin && m.installed) : m.installed;
    const gb = dlMode && m.dl ? m.dl.gb : m.download_gb;
    return `
    <div class="model-card ${m.active ? "active" : ""}">
      <div class="top"><span class="name">${esc(m.name)}</span><span class="vendor">${esc(m.vendor)}</span><span class="spacer"></span>
        ${m.id === rec.model ? '<span class="badge green">내 PC 추천</span>' : ""}<span class="badge ${m.kind === "embed" ? "purple" : "blue"}">${esc(m.badge)}</span></div>
      <div class="desc">${esc(m.desc)}</div>
      <div class="meta"><span class="badge">약 ${gb}GB</span><span class="badge">RAM ${m.min_ram_gb}GB+</span>
        <span class="badge">${esc(m.license)}</span><span class="badge">${esc(m.korean)}</span>${m.variant ? `<span class="badge green">${esc(m.variant)}</span>` : ""}${m.gov ? '<span class="badge blue" title="행정안전부 AI 공통기반 지원(또는 지원 예정) 모델 계열">공통기반 지원</span>' : ""}
        ${m.installed && m.installed_id !== m.id && m.installed_id !== m.id + ":latest" ? `<span class="badge">설치됨: ${esc(m.installed_id)}</span>` : ""}</div>
      ${m.fits ? "" : '<div class="warn">⚠ 이 PC 메모리로는 느리거나 실행되지 않을 수 있습니다</div>'}
      <div class="actions">
        ${installed
          ? (m.active ? `<span class="badge green">${m.kind === "embed" ? "검색에 사용 중" : "사용 중"}</span>` : `<button class="btn primary sm" data-use="${esc(m.installed_id)}">사용</button>`) +
            `<button class="btn ghost sm danger" data-mdel="${esc(m.installed_id)}" title="${esc(m.installed_id)} 삭제">${svg("trash")}</button>`
          : dlMode
            ? (m.can_download ? `<button class="btn primary sm" data-dl="${esc(m.id)}">${svg("download")} 받기</button>` : "") +
              (m.ollama_blob ? `<button class="btn sm" data-oimport="${esc(m.id)}" title="Ollama로 받아 둔 ${esc(m.ollama_blob)}를 복사">Ollama에서 가져오기</button>` : "") +
              `<button class="btn ghost sm" data-gguf="${esc(m.id)}" title="이미 받은 .gguf 파일을 지정">파일 직접 지정</button>`
          : m.install === "gguf"
            ? `<button class="btn sm" data-gguf="${esc(m.id)}">${svg("download")} GGUF 등록</button>`
            : `<button class="btn sm" data-pull="${esc(m.id)}">${svg("download")} 받기</button>`}
      </div>
    </div>`; }).join("");
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
  } catch (e) { toast(e.message, "err", e.message.length > 120 ? 20000 : 8000); }
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
// 파일·폴더를 PC 프로그램으로 연다. 여는 프로그램이 없는 등 열 수 없으면 이유를 알려 준다
async function openPath(path, missing = "파일을 찾을 수 없습니다 (옮겨졌거나 지워졌을 수 있습니다)") {
  try { const ok = await api("open_path", path); if (!ok) toast(missing, "info", 5000); return ok; }
  catch (e) { toast(e.message, "err", 8000); return false; }
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
    const o = t.closest("[data-open]"); if (o) { await openPath(o.dataset.open); return; }
    const pv = t.closest("[data-preview]"); if (pv) return previewFile(pv.dataset.preview);
    const cite = t.closest(".cite");
    if (cite) {
      const src = $(`.source[data-n="${cite.dataset.n}"]`, cite.closest(".msg"));
      if (src) { src.classList.add("open", "flash"); src.scrollIntoView({ behavior: "smooth", block: "nearest" }); setTimeout(() => src.classList.remove("flash"), 1200); }
      return;
    }
    const src = t.closest(".source"); if (src) return src.classList.toggle("open");
  });

  // 오늘
  // Q&A 화면이 대화 기록을 다 불러온 뒤에 질문한다 (먼저 질문하면 기록을 다시 그리며 방금 보낸 질문·답변이 지워졌다)
  $("#home-ask-form").addEventListener("submit", async (e) => {
    e.preventDefault(); const q = $("#home-ask").value; $("#home-ask").value = "";
    try { await go("ask"); } catch { /* 기록을 못 불러와도 질문은 보낸다 */ }
    ask(q);
  });
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
  segmented($("#collect-mode"), (v) => { $$(".mode-pane").forEach((p) => p.classList.toggle("on", p.dataset.mode === v)); if (v === "window") loadWindows(); });
  $("#win-refresh").addEventListener("click", loadWindows);
  $("#win-foreground").addEventListener("change", async (e) => {
    await api("save_settings", { capture_foreground: e.target.checked });
    toast(e.target.checked ? "PC저장을 자동으로 누릅니다 (저장 창이 잠깐 앞에 뜹니다)" : "창을 앞으로 가져오지 않고 뒤에서만 읽습니다", "info");
  });
  $("#win-filter").addEventListener("input", renderWindows);
  $("#win-list").addEventListener("click", (e) => { const li = e.target.closest("[data-hwnd]"); if (li) { winSel = Number(li.dataset.hwnd); renderWindows(); } });
  $("#win-list").addEventListener("dblclick", (e) => { if (e.target.closest("[data-hwnd]")) $("#win-capture").click(); });
  $("#win-capture").addEventListener("click", () => { if (winSel) doCollect("capture_window", [winSel, $("#collect-title").value, $("#collect-ai").checked]); });
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
  // 본문 붙여넣기: 웹 페이지에서 복사하면 HTML(표·붙임 링크)도 함께 받아 둔다
  let pasteHtml = "";
  const pasteInfo = () => {
    const t = $("#paste-text").value.trim();
    $("#paste-collect").disabled = t.length < 10;
    $("#paste-info").textContent = t ? `${t.length.toLocaleString()}자${pasteHtml ? " · 웹 서식 포함" : ""}` : "";
  };
  $("#paste-text").addEventListener("paste", (e) => {
    const h = e.clipboardData && e.clipboardData.getData("text/html");
    pasteHtml = h && h.length < 3000000 ? h : "";
    setTimeout(pasteInfo, 0);
  });
  $("#paste-text").addEventListener("input", () => { if (!$("#paste-text").value.trim()) pasteHtml = ""; pasteInfo(); });
  $("#paste-clear").addEventListener("click", () => { $("#paste-text").value = ""; pasteHtml = ""; pasteInfo(); });
  $("#paste-collect").addEventListener("click", async () => {
    const text = $("#paste-text").value, html = pasteHtml;
    await doCollect("collect_text", [text, title(), useAI(), html]);
    $("#paste-text").value = ""; pasteHtml = ""; pasteInfo();
  });
  $("#open-root").addEventListener("click", async () => { const s = await api("get_settings"); await openPath(s._download_root, "아직 폴더가 없습니다. 공문을 먼저 수집하세요."); });

  // 시트
  $("#nd-close").addEventListener("click", closeSheet);
  $("#nd-body").addEventListener("click", (e) => {
    const b = e.target.closest("[data-upload-notice]");
    if (!b) return;
    const n = currentNotice || {};
    openUpload(Number(b.dataset.uploadNotice), (n.attachments || []).filter((f) => !f.ok).map((f) => f.name), false);
  });
  $("#up-close").addEventListener("click", closeUpload);
  $("#up-later").addEventListener("click", closeUpload);
  $("#up-pick").addEventListener("click", async () => {
    if (!state.info.native) return toast("브라우저 모드에서는 파일을 끌어다 놓아 주세요", "info");
    uploadAttachments(await pickFiles(true));
  });
  setupDrop($("#drop-upload"), uploadAttachments);
  $("#sheet").addEventListener("click", (e) => { if (e.target.id === "sheet") closeSheet(); });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!$("#pv-sheet").classList.contains("hidden")) return closePreview();   // 미리보기부터 닫는다
    closeSheet();
  });
  $("#pv-close").addEventListener("click", closePreview);
  $("#pv-sheet").addEventListener("click", (e) => { if (e.target.id === "pv-sheet") closePreview(); });
  $("#pv-open").addEventListener("click", async () => { if (previewPath) await openPath(previewPath); });
  $("#pv-copy").addEventListener("click", async () => { await copyText($("#pv-body").textContent); toast("글자를 복사했습니다", "ok"); });
  $("#nd-folder").addEventListener("click", () => currentNotice && openPath(currentNotice.folder, "공문 폴더가 없습니다 (옮겨졌거나 지워졌을 수 있습니다)"));
  $("#nd-mail").addEventListener("click", async () => {
    if (!currentNotice) return;
    const id = currentNotice.id, ev = (currentNotice.analysis || {}).event || {};
    closeSheet(); go("mail"); await loadMail(); $("#mc-notice").value = String(id);
    // 공문 종류에 맞는 양식: 행사·교육 안내면 '행사 참석 안내', 아니면 '부서 제출 요청'
    const want = ev.name ? "행사" : "제출 요청";
    const t = state.templates.find((x) => x.name.includes(want));
    if (t) $("#mc-template").value = String(t.id);
    makeMail();
  });
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
  $("#export-ics").addEventListener("click", async () => { const p = await api("export_ics"); toast(`일정 파일을 저장했습니다: ${baseName(p)} (Outlook 등에서 열기)`, "ok", 6000); openPath(p.replace(/[\\/][^\\/]+$/, "")); });

  // 메일
  $("#rp-template").addEventListener("change", renderTplInfo);
  $("#rp-make").addEventListener("click", () => makeReport());
  $("#rp-pick").addEventListener("click", async () => addReportTemplates(await pickFiles(true)));
  $("#rp-del").addEventListener("click", async () => { const n = $("#rp-template").value; if (n && confirm(`'${n}' 양식을 삭제할까요?`)) { await api("delete_report_template", n); loadReport(); } });
  $("#rp-open").addEventListener("click", () => state.report && openPath(state.report.path));
  $("#rp-folder").addEventListener("click", () => state.report && openPath(state.report.folder));
  setupDrop($("#drop-report"), addReportTemplates);
  $("#nd-report").addEventListener("click", async () => { if (!currentNotice) return; const id = currentNotice.id; closeSheet(); go("report"); await loadReport(); $("#rp-notice").value = String(id); });
  segmented($("#mail-mode"), (v) => $$(".mail-pane").forEach((p) => p.classList.toggle("on", p.dataset.mode === v)));
  $("#mc-make").addEventListener("click", () => makeMail().catch((e) => toast(e.message, "err")));
  $("#mc-copy").addEventListener("click", async () => { await copyText(`제목: ${$("#mc-subject").value}\n\n${$("#mc-body").value}`); toast("메일 내용을 복사했습니다", "ok"); });
  $("#mc-mailto").addEventListener("click", async () => {
    // 메일 프로그램이 안 뜨거나(설정 안 된 PC) 본문이 길어 제목만 넘어가도 바로 붙여 넣을 수 있게 본문은 늘 복사해 둔다
    await copyText($("#mc-body").value);
    try {
      const r = await api("open_mail", $("#mc-subject").value, $("#mc-body").value);
      toast(r.with_body ? "메일 프로그램을 엽니다. 열리지 않으면 복사해 둔 본문을 메일에 붙여 넣으세요."
        : "본문이 길어 제목만 전달합니다. 본문은 복사해 두었으니 메일에 붙여 넣으세요.", "info", 7000);
    } catch (e) { toast(e.message, "err", 7000); }
  });
  $("#mc-save").addEventListener("click", async () => { const nid = $("#mc-notice").value; const p = await api("save_mail_draft", $("#mc-subject").value, $("#mc-body").value, nid ? Number(nid) : null); toast(`저장했습니다: ${p}`, "ok", 6000); });
  $("#mc-polish").addEventListener("click", async () => {
    const body = $("#mc-body").value;
    if (!body.trim()) return toast("먼저 메일 초안을 만들어 주세요", "info");
    // 다듬는 동안에는 쓰는 중인 글이 보이므로, 덜 된 글을 저장·복사·전송하지 못하게 잠근다
    const lock = ["#mc-polish", "#mc-save", "#mc-copy", "#mc-mailto", "#mc-make"].map((s) => $(s)).filter(Boolean);
    lock.forEach((b) => { b.disabled = true; });
    $("#mc-body").readOnly = true;
    try { const r = await runJob("polish_mail", [body], (st) => { if (st.text) $("#mc-body").value = st.text; }); $("#mc-body").value = r.body; toast("AI가 문장을 다듬었습니다. 내용을 확인해 주세요.", "ok"); }
    catch (e) { $("#mc-body").value = body; toast(e.message, "err"); }
    finally { lock.forEach((b) => { b.disabled = false; }); $("#mc-body").readOnly = false; }
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
  $("#lib-docs").addEventListener("change", async (e) => {
    const sel = e.target.closest("[data-cat]");
    if (!sel) return;
    try { await api("set_regulation_category", sel.dataset.cat, sel.value); toast(`분류를 '${sel.value}'(으)로 바꿨습니다`, "ok"); }
    catch (er) { toast(er.message, "err"); loadLibrary(); }
  });
  $("#lib-docs").addEventListener("click", async (e) => {
    const rm = e.target.closest("[data-rmdoc]"), rp = e.target.closest("[data-replace]");
    if (rm) {
      const managed = rm.dataset.managed === "1";
      const name = baseName(rm.dataset.rmdoc);
      if (!confirm(managed ? `'${name}' 규정을 저장소에서 삭제할까요?\n(프로그램 폴더의 사본만 지우며 처음 추가한 원본 파일은 그대로 있습니다)`
        : `'${name}' 규정을 저장소에서 뺄까요?\n(연결한 폴더의 원본 파일은 지우지 않고 검색·안내에서만 제외합니다. 아래 목록에서 다시 포함할 수 있습니다)`)) return;
      try {
        const r = await api("delete_regulation", rm.dataset.rmdoc);
        toast(r.mode === "deleted" ? `'${r.name}'을(를) 삭제했습니다` : `'${r.name}'을(를) 저장소에서 뺐습니다`, "ok");
      } catch (er) { toast(er.message, "err"); }
      return loadLibrary();
    }
    if (rp) {
      let p = "";
      if (state.info.native) { const r = await api("pick_files", false); p = r && r[0]; }
      else p = prompt("개정된 규정 파일의 경로를 입력하세요", "") || "";
      if (!p) return;
      try {
        await runJob("replace_regulation", [rp.dataset.replace, p], async () => { const r = await api("list_documents"); showProgress(r.progress); });
        showProgress(null);
        toast(`'${baseName(p)}'(으)로 바꿨습니다`, "ok");
      } catch (er) { toast(er.message, "err"); showProgress(null); }
      return loadLibrary();
    }
  });
  $("#lib-excluded").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-restore]");
    if (!b) return;
    try { await runJob("restore_regulation", [b.dataset.restore]); toast("다시 저장소에 넣었습니다", "ok"); }
    catch (er) { toast(er.message, "err"); }
    loadLibrary();
  });
  $("#lib-dirs").addEventListener("click", async (e) => { const b = e.target.closest("[data-rmdir]"); if (b && confirm("저장소 목록에서 제거할까요? (파일은 삭제되지 않습니다)")) { await api("remove_regulation_dir", b.dataset.rmdir); reindex(false); } });
  setupDrop($("#drop-lib"), importLibFiles);
  $("#lib-pick-files").addEventListener("click", async () => importLibFiles(await pickFiles(true)));

  bindGuide();

  // 설정
  // 테마는 누르면 바로 바뀌어 보이므로 바로 저장한다 (저장 버튼을 안 누르고 나가면 다음 실행 때 되돌아가던 문제)
  segmented($("#set-theme"), async (t) => {
    applyTheme(t);
    try { state.settings = await api("save_settings", { theme: t }); } catch (e) { toast(e.message, "err"); }
  });
  $("#set-save").addEventListener("click", saveSettings);
  $("#set-ai-check").addEventListener("click", () => { refreshAI(); loadModels(); });
  $("#model-grid").addEventListener("click", async (e) => {
    const u = e.target.closest("[data-use]"), p = e.target.closest("[data-pull]"), d = e.target.closest("[data-mdel]"), g = e.target.closest("[data-gguf]");
    const oi = e.target.closest("[data-oimport]"), dl = e.target.closest("[data-dl]");
    if (e.target.closest("[data-engine-dl]")) {
      if (!confirm("AI 실행 엔진(llama.cpp, 약 30MB)을 인터넷에서 받습니다. 받아 둔 모델 파일은 그대로 씁니다.")) return;
      return modelJob("install_engine", [], "AI 엔진을 넣었습니다. 이제 AI 분석을 쓸 수 있습니다.");
    }
    if (e.target.closest("[data-engine-pick]")) {
      let p = "";
      if (state.info.native) { const r = await api("pick_files", false); p = r && r[0]; }
      else p = prompt("llama.cpp 압축 파일(.zip)이나 llama-server.exe의 경로를 입력하세요", "") || "";
      if (!p) return;
      return modelJob("import_engine", [p], "AI 엔진을 넣었습니다. 이제 AI 분석을 쓸 수 있습니다.");
    }
    if (dl) {
      const m = (state.catalog || []).find((x) => x.id === dl.dataset.dl) || {};
      const size = m.dl ? m.dl.gb : m.download_gb;
      if (!confirm(`${m.name} 모델(약 ${size}GB)을 인터넷에서 받습니다.\n내장 AI 엔진이 없으면 엔진(약 30MB)도 함께 받습니다.\n받는 동안 다른 작업을 해도 되며, 끊기면 다시 누를 때 이어서 받습니다.`)) return;
      return modelJob("download_model", [m.id], `${m.name} 모델을 받았습니다. 바로 사용할 수 있습니다 (Ollama 불필요).`);
    }
    if (oi) return modelJob("import_from_ollama", [oi.dataset.oimport], "Ollama의 모델 파일을 내장 엔진으로 옮겼습니다. '사용'을 눌러 적용하세요.");
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
      const q = m.quant || "Q4_K_M";
      $("#gguf-quant").textContent = q; $("#gguf-hfq").textContent = `hf.co/사용자/저장소:${q}`;
      $("#gguf-path").placeholder = `C:\\Users\\...\\Downloads\\${m.dl ? m.dl.file : "모델-" + q + ".gguf"}` + (state.engine === "builtin" ? "" : " 또는 hf.co/...");
      $("#gguf-hf").dataset.href = m.hf || "https://huggingface.co";
      $("#gguf-box").classList.remove("hidden");
      $("#gguf-path").focus();
    }
  });
  segmented($("#engine-seg"), async (v) => {
    try { await api("set_engine", v); toast(v === "builtin" ? "내장 엔진을 사용합니다" : v === "ollama" ? "Ollama를 사용합니다" : "엔진을 자동으로 선택합니다", "ok"); }
    catch (er) { toast(er.message, "err"); }
    loadModels(); refreshAI();
  });
  $("#gguf-hf").addEventListener("click", (e) => { e.preventDefault(); window.open(e.target.dataset.href, "_blank"); });
  $("#gguf-pick").addEventListener("click", async () => {
    if (!state.info.native) return toast("브라우저 모드에서는 파일 경로를 직접 입력해 주세요", "info");
    const p = await api("pick_files", false); if (p && p[0]) $("#gguf-path").value = p[0];
  });
  $("#gguf-go").addEventListener("click", () => {
    const v = $("#gguf-path").value.trim();
    if (!v || !ggufTarget) return toast("GGUF 파일 경로를 입력하세요", "info");
    if (/^hf\.co\//i.test(v) && state.engine === "builtin") return toast("내장 엔진은 파일 경로(.gguf)를 입력해 주세요", "info");
    if (/^hf\.co\//i.test(v)) return modelJob("pull_model", [v, ggufTarget], `${ggufTarget} 모델을 받았습니다. '사용'을 눌러 적용하세요.`);
    modelJob("import_gguf", [v, ggufTarget], `${ggufTarget} 모델을 등록했습니다. '사용'을 눌러 적용하세요.`);
  });
  $("#set-root-pick").addEventListener("click", async () => { if (!state.info.native) return toast("브라우저 모드에서는 경로를 직접 입력해 주세요", "info"); const p = await api("pick_folder"); if (p) $("#set-download_root").value = p; });
}

// ------------------------------------------------------------------ 시작
// 창이 열려 있다는 신호: 프로그램은 이 신호가 끊기면 창이 닫힌 것으로 보고 종료한다
async function heartbeat() { try { await api("heartbeat"); } catch (e) { /* 다음 신호에서 다시 (토큰이 바뀌었으면 api()가 화면을 새로 불러온다) */ } }
heartbeat(); setInterval(heartbeat, 5000);

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
