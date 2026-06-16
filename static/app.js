"use strict";

const $ = (id) => document.getElementById(id);

const els = {
  dropzone: $("dropzone"),
  pdfInput: $("pdf-input"),
  dzEmpty: document.querySelector(".dropzone-empty"),
  dzFilled: document.querySelector(".dropzone-filled"),
  chipName: document.querySelector(".chip-name"),
  clearFile: $("clear-file"),
  togglePaste: $("toggle-paste"),
  resumeText: $("resume-text"),
  jdText: $("jd-text"),
  submit: $("submit"),
  formHint: $("form-hint"),
  formCard: $("form-card"),
  progress: $("progress"),
  stageText: $("stage-text"),
  results: $("results"),
  engine: $("engine"),
  engineHint: $("engine-hint"),
  providerNote: $("provider-note"),
  error: $("error"),
  errorText: $("error-text"),
  errorCountdown: $("error-countdown"),
  useAlternate: $("use-alternate"),
  errorRetry: $("error-retry"),
  restart: $("restart"),
};

let selectedFile = null;
let countdownTimer = null;
let provider = "auto";

const PROVIDER_LABEL = { gemini: "Google Gemini", groq: "Groq", auto: "Auto" };

/* ---------- engine (provider) selector ---------- */
function setProvider(p) {
  provider = p;
  els.engine.querySelectorAll(".seg").forEach((b) =>
    b.classList.toggle("active", b.dataset.provider === p)
  );
  const hints = {
    auto: "Auto picks whichever is available.",
    gemini: "Google Gemini — may hit free-tier limits.",
    groq: "Groq — fast, generous free tier.",
  };
  els.engineHint.textContent = hints[p] || "";
}
els.engine.querySelectorAll(".seg").forEach((b) =>
  b.addEventListener("click", () => setProvider(b.dataset.provider))
);

/* ---------- input handling ---------- */

function setFile(file) {
  selectedFile = file;
  if (file) {
    els.chipName.textContent = file.name;
    els.dzEmpty.hidden = true;
    els.dzFilled.hidden = false;
  } else {
    els.pdfInput.value = "";
    els.dzEmpty.hidden = false;
    els.dzFilled.hidden = true;
  }
  refreshValidity();
}

els.dropzone.addEventListener("click", (e) => {
  if (e.target === els.clearFile) return;
  els.pdfInput.click();
});
els.dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); els.pdfInput.click(); }
});
els.pdfInput.addEventListener("change", () => {
  const f = els.pdfInput.files[0];
  if (f) validateAndSet(f);
});
els.clearFile.addEventListener("click", (e) => { e.stopPropagation(); setFile(null); });

["dragover", "dragenter"].forEach((ev) =>
  els.dropzone.addEventListener(ev, (e) => { e.preventDefault(); els.dropzone.classList.add("drag"); })
);
["dragleave", "drop"].forEach((ev) =>
  els.dropzone.addEventListener(ev, (e) => { e.preventDefault(); els.dropzone.classList.remove("drag"); })
);
els.dropzone.addEventListener("drop", (e) => {
  const f = e.dataTransfer.files[0];
  if (f) validateAndSet(f);
});

function validateAndSet(file) {
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) {
    showHint("That's not a PDF. Upload a PDF, or paste your resume text instead.");
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    showHint("That file is large for a resume (>10MB). Try a shorter, text-based PDF.");
    return;
  }
  setFile(file);
}

els.togglePaste.addEventListener("click", () => {
  const showing = !els.resumeText.hidden;
  els.resumeText.hidden = showing;
  els.togglePaste.textContent = showing
    ? "…or paste resume text instead"
    : "…or upload a PDF instead";
  // Revealing the paste box switches input mode — drop any selected file so the
  // two inputs can't both be set (file would otherwise silently win at submit).
  if (!showing) { setFile(null); els.resumeText.focus(); }
  refreshValidity();
});

els.resumeText.addEventListener("input", refreshValidity);
els.jdText.addEventListener("input", refreshValidity);

function hasResume() {
  const pasted = !els.resumeText.hidden && els.resumeText.value.trim().length > 0;
  return Boolean(selectedFile) || pasted;
}

function refreshValidity() {
  const ok = hasResume() && els.jdText.value.trim().length > 0;
  els.submit.disabled = !ok;
  if (ok) showHint("Ready when you are.");
  else if (!hasResume()) showHint("Add your resume (PDF or pasted text).");
  else showHint("Paste the job description to continue.");
}

function showHint(msg) { els.formHint.textContent = msg; }

/* ---------- staged progress ---------- */

const STAGES = [
  "Reading your resume…",
  "Understanding the role…",
  "Scoring your fit…",
  "Rewriting your bullets…",
];
let stageTimer = null;

function startStages() {
  let i = 0;
  els.stageText.textContent = STAGES[0];
  // Optimistic narration — a sync request can't report true per-agent progress,
  // so we advance on a timer to keep the long wait from feeling frozen.
  stageTimer = setInterval(() => {
    i = Math.min(i + 1, STAGES.length - 1);
    els.stageText.textContent = STAGES[i];
  }, 6000);
}
function stopStages() { clearInterval(stageTimer); stageTimer = null; }

/* ---------- submit ---------- */

els.submit.addEventListener("click", run);
els.errorRetry.addEventListener("click", reset);
els.restart.addEventListener("click", reset);

function show(section) {
  for (const s of [els.formCard, els.progress, els.results, els.error]) s.hidden = true;
  section.hidden = false;
}

async function run() {
  clearInterval(countdownTimer);
  show(els.progress);
  startStages();

  const jd = els.jdText.value.trim();
  const usingPaste = !els.resumeText.hidden && els.resumeText.value.trim().length > 0 && !selectedFile;

  try {
    let res;
    if (selectedFile) {
      const fd = new FormData();
      fd.append("resume_pdf", selectedFile);
      fd.append("job_description", jd);
      fd.append("provider", provider);
      res = await fetch("/tailor/upload", { method: "POST", body: fd });
    } else {
      res = await fetch("/tailor", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resume_text: els.resumeText.value.trim(), job_description: jd, provider }),
      });
    }

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      stopStages();
      // 429 = model rate-limited. Show when it'll be ready, with a live countdown.
      if (res.status === 429) return failRateLimited(body.detail || {});
      // 422 = PDF unreadable. Nudge the user to the paste box.
      if (res.status === 422 && !usingPaste) revealPaste();
      const detail =
        typeof body.detail === "string" ? body.detail : `Something went wrong (HTTP ${res.status}).`;
      return fail(detail);
    }

    const data = await res.json();
    stopStages();
    // A pipeline step can fail (transient error, rate limit) leaving its state key
    // unset, so the API returns 200 with null sections. Don't render a blank page.
    if (!data.analysis || !data.tailored) {
      return fail(
        "The AI pipeline didn't return a complete result — this can happen on a " +
        "transient error or an API rate limit. Please try again in a moment."
      );
    }
    render(data);
    show(els.results);
  } catch (err) {
    stopStages();
    fail("Couldn't reach the server. Is it still running? " + err.message);
  }
}

function fail(msg) {
  clearInterval(countdownTimer);
  els.errorText.textContent = msg;
  els.errorCountdown.hidden = true;
  els.useAlternate.hidden = true;
  els.errorRetry.disabled = false;
  show(els.error);
}

// Rate-limited: show the message + a live countdown to when the app is ready,
// and keep "Try again" disabled until then.
function failRateLimited(info) {
  clearInterval(countdownTimer);
  els.errorText.textContent = info.message || "The AI service is rate-limited right now.";

  // One-tap escape hatch: if another engine wasn't tried, offer to use it now.
  if (info.alternate) {
    els.useAlternate.hidden = false;
    els.useAlternate.textContent = `⚡ Use ${info.alternate_label || info.alternate} now`;
    els.useAlternate.onclick = () => { setProvider(info.alternate); run(); };
  } else {
    els.useAlternate.hidden = true;
  }

  const readyAt = info.ready_at
    ? new Date(info.ready_at).getTime()
    : Date.now() + (info.retry_after_seconds || 60) * 1000;
  const localTime = new Date(readyAt).toLocaleString(undefined, {
    hour: "numeric", minute: "2-digit", month: "short", day: "numeric",
  });

  els.errorCountdown.hidden = false;
  show(els.error);

  const tick = () => {
    const ms = readyAt - Date.now();
    if (ms <= 0) {
      clearInterval(countdownTimer);
      els.errorCountdown.textContent = "Ready now — go ahead and try again.";
      els.errorCountdown.classList.add("ready");
      els.errorRetry.disabled = false;
      return;
    }
    els.errorCountdown.classList.remove("ready");
    els.errorRetry.disabled = true;
    els.errorCountdown.textContent = `Ready in ${fmtCountdown(ms)}  ·  ~${localTime}`;
  };
  tick();
  countdownTimer = setInterval(tick, 1000);
}

function fmtCountdown(ms) {
  const s = Math.ceil(ms / 1000);
  if (s < 90) return `${s}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h >= 1) return `${h}h ${m}m`;
  return `${m}m ${s % 60}s`;
}

function revealPaste() {
  // Drop the unreadable file so the user's pasted text is actually used on retry
  // (the submit handler prefers selectedFile, so a stale file would re-trigger 422).
  setFile(null);
  els.resumeText.hidden = false;
  els.togglePaste.textContent = "…or upload a PDF instead";
}

function reset() {
  show(els.formCard);
  refreshValidity();
}

/* ---------- rendering ---------- */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}
// LLM bullets come back with **markdown bold** — render emphasis after escaping.
function fmt(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>"); }

function render(data) {
  const analysis = data.analysis || {};
  const tailored = data.tailored || {};

  // Tell the user which engine ran, and call out a transparent fallback.
  if (data.fell_back) {
    els.providerNote.textContent =
      `⚡ The preferred engine was busy — tailored with ${PROVIDER_LABEL[data.provider_used] || data.provider_used} instead.`;
    els.providerNote.hidden = false;
  } else if (data.provider_used) {
    els.providerNote.textContent = `Tailored with ${PROVIDER_LABEL[data.provider_used] || data.provider_used}.`;
    els.providerNote.hidden = false;
  } else {
    els.providerNote.hidden = true;
  }

  // score ring (count-up + arc)
  const score = Math.max(0, Math.min(100, Number(analysis.match_score) || 0));
  const ring = document.querySelector(".score-ring");
  ring.style.setProperty("--pct", score);
  animateCount($("score-num"), score);
  $("score-summary").textContent = analysis.summary || "";

  const chips = (analysis.matches || [])
    .map((m) => `<span class="skill ${esc(m.status)}"><span class="dot"></span>${esc(m.skill)}</span>`)
    .join("");
  $("skill-chips").innerHTML = chips;

  // tailored bullets diff
  const bullets = (tailored.tailored_bullets || [])
    .map(
      (b) => `
      <div class="bullet">
        <div class="bullet-row">
          <div class="bullet-label">Before</div>
          <div class="bullet-orig">${esc(b.original)}</div>
        </div>
        <div class="bullet-row">
          <div class="bullet-label">After</div>
          <div class="bullet-new">${fmt(b.tailored)}</div>
        </div>
        <div class="bullet-foot">
          <span class="rationale">${esc(b.rationale)}</span>
          <button class="copy-btn" data-copy="${esc(b.tailored).replace(/\*\*/g, "")}">Copy</button>
        </div>
      </div>`
    )
    .join("");
  $("bullets").innerHTML = bullets || '<p class="section-sub">No bullets were rewritten.</p>';

  // honest gaps
  const gaps = tailored.honest_gaps || [];
  if (gaps.length) {
    $("gaps-list").innerHTML = gaps.map((g) => `<li>${esc(g)}</li>`).join("");
    $("gaps-card").hidden = false;
  } else {
    $("gaps-card").hidden = true;
  }

  // ats keywords
  const ats = tailored.ats_keywords_to_add || [];
  if (ats.length) {
    $("ats-chips").innerHTML = ats.map((k) => `<span class="ats">${esc(k)}</span>`).join("");
    $("ats-card").hidden = false;
  } else {
    $("ats-card").hidden = true;
  }

  wireCopyButtons();
}

function wireCopyButtons() {
  document.querySelectorAll(".copy-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(btn.dataset.copy);
      } catch {
        // navigator.clipboard is undefined on non-secure origins (http on a LAN
        // IP). Fall back to the legacy execCommand copy so it still works there.
        const ta = document.createElement("textarea");
        ta.value = btn.dataset.copy;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); } catch (_) {}
        ta.remove();
      }
      const old = btn.textContent;
      btn.textContent = "Copied ✓";
      btn.classList.add("done");
      setTimeout(() => { btn.textContent = old; btn.classList.remove("done"); }, 1500);
    });
  });
}

function animateCount(el, target) {
  let cur = 0;
  const step = Math.max(1, Math.round(target / 30));
  const t = setInterval(() => {
    cur = Math.min(target, cur + step);
    el.textContent = cur;
    if (cur >= target) clearInterval(t);
  }, 20);
}

refreshValidity();
