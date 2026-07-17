"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Msg = { role: "user" | "axon"; text: string; t?: number };
type Ix = { state: string; count: number };
type Auth = { cli: boolean; logged_in: boolean; checked: boolean; reason?: string; detail?: string };
type St = { state: string; model: string; mic: boolean; history: Msg[]; index?: Ix; auth?: Auth };
type GNode = { id: string; label: string; group: string; size: number; hub?: boolean; root?: boolean };
type GLink = { source: string; target: string };
type Graph = {
  title: string; nodes: GNode[]; links: GLink[];
  groups: { name: string; count: number }[];
  hubs: { label: string; size: number }[];
  stats: { notes: number; connections: number };
};

const SUB: Record<string, string> = {
  idle: "all systems online, sir", listening: "listening, sir…",
  thinking: "processing your request…", speaking: "speaking…", error: "a fault occurred",
};
const BIG: Record<string, string> = {
  idle: "STANDING BY", listening: "LISTENING", thinking: "THINKING", speaking: "SPEAKING", error: "ERROR",
};
const TABS: [string, string][] = [["idle", "IDLE"], ["listening", "LISTEN"], ["thinking", "THINK"], ["speaking", "SPEAK"]];
const GC: Record<string, string> = {
  core: "#8fe9ff", project: "#b06cff", concept: "#ffd23f", skill: "#21d4fd", tool: "#2bd576", note: "#6b7fa0",
  folder: "#ffb020", document: "#3b82f6", image: "#22d3ee", video: "#ef4444", audio: "#2bd576",
  code: "#f59e0b", archive: "#a855f7", file: "#64748b",
};
const colorOf = (g: string) => GC[g] || "#64748b";
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

// Common speech-recognition mishearings of "Axon" — matching only the exact
// word made wake-word mode miss constantly. Longest/most-specific first so a
// phrase like "exxon" doesn't get cut short by a shorter false alias.
const WAKE_ALIASES = ["axon", "exxon", "aksen", "akson", "axen", "axan", "axion", "ashon"];
function findWake(text: string): { idx: number; len: number } | null {
  const low = text.toLowerCase();
  let best: { idx: number; len: number } | null = null;
  for (const alias of WAKE_ALIASES) {
    const m = new RegExp(`\\b${alias}\\b`, "i").exec(low);
    if (m && (best === null || m.index < best.idx)) best = { idx: m.index, len: alias.length };
  }
  return best;
}
const clock = (s = 0) => [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60].map((x) => String(x).padStart(2, "0")).join(":");

export default function Home() {
  const [st, setSt] = useState<St>({ state: "idle", model: "", mic: false, history: [] });
  const [text, setText] = useState("");
  const [graphData, setGraphData] = useState<Graph | null>(null);
  const [graphLoaded, setGraphLoaded] = useState(0);
  const [selNode, setSelNode] = useState<GNode | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<string[]>([]);
  const [uptime, setUptime] = useState(0);
  const [rechecking, setRechecking] = useState(false);
  const [listening, setListening] = useState(false);
  const [wakeMode, setWakeMode] = useState(false);
  const [voiceLang, setVoiceLang] = useState("en-US");
  const recogRef = useRef<any>(null);
  const wakeRef = useRef<any>(null);
  const wakeModeRef = useRef(false);
  const armedUntilRef = useRef(0);   // after a bare "Axon", accept the next utterance as the command
  const prevAxonCount = useRef(0);

  const feedRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);
  const selRef = useRef<GNode | null>(null);
  const hiddenRef = useRef<Set<string>>(new Set());
  const askRef = useRef<((n: GNode) => void) | null>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try { const d = (await (await fetch("/api/state", { cache: "no-store" })).json()) as St; if (alive) setSt(d); } catch {}
    };
    tick();
    const id = setInterval(tick, 250);
    return () => { alive = false; clearInterval(id); };
  }, []);
  useEffect(() => { const id = setInterval(() => setUptime((u) => u + 1), 1000); return () => clearInterval(id); }, []);
  useEffect(() => { if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight; }, [st.history.length]);
  useEffect(() => { selRef.current = selNode; }, [selNode]);
  useEffect(() => { hiddenRef.current = hidden; }, [hidden]);
  useEffect(() => { wakeModeRef.current = wakeMode; }, [wakeMode]);

  // desktop notifications: ping when AXON replies while the tab isn't focused
  useEffect(() => {
    if (typeof Notification !== "undefined" && Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }
  }, []);
  useEffect(() => {
    const axonMsgs = st.history.filter((m) => m.role === "axon");
    if (axonMsgs.length > prevAxonCount.current) {
      const last = axonMsgs[axonMsgs.length - 1];
      if (document.hidden && typeof Notification !== "undefined" && Notification.permission === "granted") {
        try { new Notification("AXON", { body: last.text.slice(0, 200) }); } catch {}
      }
    }
    prevAxonCount.current = axonMsgs.length;
  }, [st.history]);

  useEffect(() => {
    (async () => {
      try {
        const g = (await (await fetch("/api/graph")).json()) as Graph;
        const byId: Record<string, any> = {};
        (g.nodes as any[]).forEach((n) => (byId[n.id] = n));
        (g as any).byId = byId;
        graphRef.current = g; setGraphData(g); setGraphLoaded((x) => x + 1);
      } catch {}
    })();
  }, []);

  const post = (t: string) =>
    fetch("/api/say", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: t }) }).catch(() => {});
  const clearChat = useCallback(() => { fetch("/api/clear", { method: "POST" }).catch(() => {}); }, []);
  const send = useCallback(() => {
    const t = text.trim(); if (!t) return; setText("");
    if (/^(clear|clear chat|clear history|reset chat)$/i.test(t)) { clearChat(); return; }
    post(t);
  }, [text, clearChat]);
  const askAbout = useCallback((n: GNode) => {
    if (n.root) return;
    const isFolder = n.group === "folder";
    post(isFolder
      ? `In one or two sentences, what is the folder "${n.label}" for? Path: ${n.id}`
      : `In one or two sentences, what is the file "${n.label}"? If it's text, read it and summarize. Path: ${n.id}`);
  }, []);
  useEffect(() => { askRef.current = askAbout; }, [askAbout]);

  const getSR = (): any => (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

  // browser-based push-to-talk (Web Speech API) — uses the OS mic (earbuds etc.)
  const toggleMic = () => {
    if (wakeMode) return;   // wake-word mode already owns the mic
    if (listening) { recogRef.current?.stop(); return; }
    const SR = getSR();
    if (!SR) { alert("Voice input needs Chrome or Edge (Web Speech API not available here)."); return; }
    const r = new SR();
    r.lang = voiceLang; r.interimResults = true; r.continuous = false; r.maxAlternatives = 1;
    r.onstart = () => setListening(true);
    r.onend = () => { setListening(false); recogRef.current = null; };
    r.onerror = (e: any) => { setListening(false); if (e?.error === "not-allowed") alert("Microphone permission was blocked. Allow it in the browser and try again."); };
    r.onresult = (e: any) => {
      let finalText = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) finalText += res[0].transcript;
        else setText(res[0].transcript);      // live preview while speaking
      }
      if (finalText.trim()) { setText(""); post(finalText.trim()); r.stop(); }
    };
    recogRef.current = r;
    try { r.start(); } catch {}
  };

  // hands-free "Hey Axon" — always listening; only acts on speech that
  // contains the wake word (or a close mishearing of it), so ambient
  // conversation is ignored. If you just say "Axon" and pause, the NEXT
  // utterance within a few seconds is taken as the command even though it
  // won't contain the wake word itself. Auto-restarts itself since browsers
  // stop continuous recognition after a silence gap.
  const startWakeListening = () => {
    const SR = getSR();
    if (!SR) { alert("Voice input needs Chrome or Edge (Web Speech API not available here)."); setWakeMode(false); return; }
    const r = new SR();
    r.lang = voiceLang; r.interimResults = true; r.continuous = true; r.maxAlternatives = 1;
    r.onstart = () => setListening(true);
    r.onend = () => {
      setListening(false);
      if (wakeModeRef.current) { try { r.start(); } catch {} }   // keep listening
    };
    r.onerror = (e: any) => {
      if (e?.error === "not-allowed") {
        alert("Microphone permission was blocked. Allow it in the browser and try again.");
        setWakeMode(false); wakeModeRef.current = false;
      }
      // other errors (no-speech/network) just let onend restart it
    };
    r.onresult = (e: any) => {
      const now = Date.now();
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (!res.isFinal) { setText(res[0].transcript); continue; }   // live "hearing…" preview
        const transcript = res[0].transcript.trim();
        const hit = findWake(transcript);
        if (hit) {
          const command = transcript.slice(hit.idx + hit.len).replace(/^[,.:\s]+/, "").trim();
          setText("");
          if (command) { post(command); armedUntilRef.current = 0; }
          else { armedUntilRef.current = now + 6000; }   // "Axon" alone — wait for the follow-up
        } else if (armedUntilRef.current && now <= armedUntilRef.current && transcript) {
          setText("");
          post(transcript);
          armedUntilRef.current = 0;
        } else {
          setText("");   // ambient speech with no wake word — clear the preview, ignore it
        }
      }
    };
    wakeRef.current = r;
    try { r.start(); } catch {}
  };

  const toggleWakeMode = () => {
    if (wakeMode) {
      setWakeMode(false); wakeModeRef.current = false;
      wakeRef.current?.stop(); wakeRef.current = null;
      return;
    }
    if (listening) recogRef.current?.stop();
    setWakeMode(true); wakeModeRef.current = true;
    startWakeListening();
  };

  const signIn = () => { fetch("/api/signin", { method: "POST" }).catch(() => {}); };
  const recheck = async () => {
    setRechecking(true);
    try { await fetch("/api/recheck", { method: "POST" }); } catch {}
    setRechecking(false);
  };
  const openResult = (p: string) =>
    fetch("/api/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: p }) }).catch(() => {});
  const onSearch = (q: string) => {
    const query = q.trim();
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (!query) { setResults([]); return; }
    searchTimer.current = setTimeout(async () => {
      try { const r = await (await fetch(`/api/find?q=${encodeURIComponent(query)}&limit=30`)).json(); setResults(r.results || []); } catch {}
      if (graphData) { const hit = graphData.nodes.find((n) => n.label.toLowerCase().includes(query.toLowerCase())); if (hit) setSelNode(hit); }
    }, 220);
  };

  // ── force graph ──
  useEffect(() => {
    const G = graphRef.current, canvas = canvasRef.current, wrap = wrapRef.current;
    if (!G || !canvas || !wrap) return;
    const ctx = canvas.getContext("2d")!;
    let cw = 0, ch = 0, dpr = 1;
    const resize = () => {
      const rect = wrap.getBoundingClientRect();
      dpr = window.devicePixelRatio || 1;
      cw = Math.max(1, rect.width); ch = Math.max(1, rect.height);
      canvas.width = Math.floor(cw * dpr); canvas.height = Math.floor(ch * dpr);
      canvas.style.width = cw + "px"; canvas.style.height = ch + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize); ro.observe(wrap);
    {
      const N = G.nodes.length, R = 24 * Math.sqrt(N) + 50;
      G.nodes.forEach((n: any, i: number) => {
        const t = Math.sqrt((i + 0.5) / N), a = i * 2.399963;
        n.x = cw / 2 + R * t * Math.cos(a); n.y = ch / 2 + R * t * Math.sin(a); n.vx = 0; n.vy = 0;
      });
    }
    let drag: any = null, downNode: any = null, moved = false, hover: any = null, raf = 0, frame = 0;
    let scale = 1, panX = 0, panY = 0, panning = false, lastX = 0, lastY = 0, downX = 0, downY = 0;
    const vis = (n: any) => !hiddenRef.current.has(n.group);
    const isNbr = (a: any, b: any) => G.links.some((l: GLink) => (l.source === a.id && l.target === b.id) || (l.target === a.id && l.source === b.id));
    const step = () => {
      const cx = cw / 2, cy = ch / 2, REP = 1600, SPRING = 0.033, LEN = 60, DAMP = 0.9, MAXV = 26, MIND2 = 120;
      for (const n of G.nodes) { n.fx = (cx - n.x) * 0.0045; n.fy = (cy - n.y) * 0.0045; }
      for (let i = 0; i < G.nodes.length; i++)
        for (let j = i + 1; j < G.nodes.length; j++) {
          const a = G.nodes[i], b = G.nodes[j];
          let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy;
          if (d2 < MIND2) { if (dx === 0 && dy === 0) { dx = (i % 7) - 3 + 0.5; dy = (j % 7) - 3 + 0.5; } d2 = MIND2; }
          const d = Math.sqrt(dx * dx + dy * dy) || 1, f = REP / d2, ux = dx / d, uy = dy / d;
          a.fx += ux * f; a.fy += uy * f; b.fx -= ux * f; b.fy -= uy * f;
        }
      for (const l of G.links as GLink[]) {
        const a = G.byId[l.source], b = G.byId[l.target]; if (!a || !b) continue;
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1, f = SPRING * (d - LEN);
        const ux = dx / d, uy = dy / d; a.fx += ux * f; a.fy += uy * f; b.fx -= ux * f; b.fy -= uy * f;
      }
      for (const n of G.nodes) {
        if (n === drag) continue;
        n.vx = (n.vx + n.fx) * DAMP; n.vy = (n.vy + n.fy) * DAMP;
        n.vx = n.vx > MAXV ? MAXV : n.vx < -MAXV ? -MAXV : n.vx;
        n.vy = n.vy > MAXV ? MAXV : n.vy < -MAXV ? -MAXV : n.vy;
        n.x += n.vx; n.y += n.vy;
      }
    };
    const fit = () => {
      let a1 = Infinity, a2 = -Infinity, b1 = Infinity, b2 = -Infinity;
      for (const n of G.nodes) { if (n.x < a1) a1 = n.x; if (n.x > a2) a2 = n.x; if (n.y < b1) b1 = n.y; if (n.y > b2) b2 = n.y; }
      if (!isFinite(a1)) return;
      const w = a2 - a1 || 1, h = b2 - b1 || 1, pad = 70;
      const s = clamp(Math.min((cw - 2 * pad) / w, (ch - 2 * pad) / h), 0.12, 2.4);
      if (!isFinite(s) || s <= 0) return;
      scale = s; panX = cw / 2 - ((a1 + a2) / 2) * scale; panY = ch / 2 - ((b1 + b2) / 2) * scale;
    };
    const draw = () => {
      const sel = selRef.current as any;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, cw, ch);
      ctx.translate(panX, panY); ctx.scale(scale, scale);
      for (const l of G.links as GLink[]) {
        const a = G.byId[l.source], b = G.byId[l.target]; if (!vis(a) || !vis(b)) continue;
        const hot = sel && (l.source === sel.id || l.target === sel.id);
        ctx.strokeStyle = hot ? "rgba(140,233,255,.75)" : "rgba(90,150,210,.12)"; ctx.lineWidth = hot ? 1.5 : 0.7;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      }
      for (const n of G.nodes) {
        if (!vis(n)) continue;
        const r = n.root ? 13 : 5 + n.size * 1.6;
        const dim = sel && sel.id !== n.id && !isNbr(sel, n);
        if (n.root) {                       // AXON centre ring
          ctx.globalAlpha = 1; ctx.strokeStyle = "rgba(140,233,255,.5)"; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.arc(n.x, n.y, r + 26, 0, 7); ctx.stroke();
        }
        ctx.globalAlpha = dim ? 0.2 : 1; ctx.fillStyle = n.root ? "#dffcff" : colorOf(n.group);
        ctx.shadowColor = n.root ? "#8fe9ff" : colorOf(n.group);
        ctx.shadowBlur = n.root ? 26 : (n === hover || (sel && sel.id === n.id)) ? 20 : (n.hub ? 8 : 0);
        ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
        if (n === hover || (sel && sel.id === n.id) || n.hub) {
          ctx.globalAlpha = dim ? 0.3 : 0.95; ctx.fillStyle = "#dfeeff";
          ctx.font = `${n.root ? "bold 13" : "11"}px Segoe UI`; ctx.textAlign = "center";
          ctx.fillText(n.label, n.x, n.y - r - 7);
        }
        ctx.globalAlpha = 1;
      }
    };
    const loop = () => { frame++; step(); if (frame < 170 && frame % 12 === 0) fit(); draw(); raf = requestAnimationFrame(loop); };
    loop();
    const at = (sx: number, sy: number) => {
      const wx = (sx - panX) / scale, wy = (sy - panY) / scale;
      for (let i = G.nodes.length - 1; i >= 0; i--) {
        const n = G.nodes[i]; if (!vis(n)) continue;
        const r = n.root ? 13 : 5 + n.size * 1.6;
        if ((wx - n.x) ** 2 + (wy - n.y) ** 2 <= (r + 6 / scale) ** 2) return n;
      }
      return null;
    };
    const onMove = (e: MouseEvent) => {
      const b = canvas.getBoundingClientRect(), sx = e.clientX - b.left, sy = e.clientY - b.top;
      if (drag) { drag.x = (sx - panX) / scale; drag.y = (sy - panY) / scale; drag.vx = 0; drag.vy = 0; if ((sx - downX) ** 2 + (sy - downY) ** 2 > 20) moved = true; }
      else if (panning) { panX += sx - lastX; panY += sy - lastY; lastX = sx; lastY = sy; }
      else { hover = at(sx, sy); canvas.style.cursor = hover ? "pointer" : "grab"; }
    };
    const onDown = (e: MouseEvent) => {
      const b = canvas.getBoundingClientRect(), sx = e.clientX - b.left, sy = e.clientY - b.top;
      const n = at(sx, sy); downX = sx; downY = sy; moved = false;
      if (n) { drag = n; downNode = n; setSelNode(n); }
      else { panning = true; lastX = sx; lastY = sy; setSelNode(null); canvas.style.cursor = "grabbing"; }
    };
    const onUp = () => { if (downNode && !moved) askRef.current?.(downNode); drag = null; downNode = null; panning = false; };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const b = canvas.getBoundingClientRect(), mx = e.clientX - b.left, my = e.clientY - b.top;
      const wx = (mx - panX) / scale, wy = (my - panY) / scale;
      scale = clamp(scale * (e.deltaY < 0 ? 1.12 : 0.89), 0.08, 5);
      panX = mx - wx * scale; panY = my - wy * scale;
    };
    canvas.addEventListener("mousemove", onMove); canvas.addEventListener("mousedown", onDown);
    canvas.addEventListener("wheel", onWheel, { passive: false }); window.addEventListener("mouseup", onUp);
    return () => {
      cancelAnimationFrame(raf); ro.disconnect(); window.removeEventListener("mouseup", onUp);
      canvas.removeEventListener("mousemove", onMove); canvas.removeEventListener("mousedown", onDown); canvas.removeEventListener("wheel", onWheel);
    };
  }, [graphLoaded]);

  const toggleGroup = (g: string) => setHidden((h) => { const n = new Set(h); if (n.has(g)) n.delete(g); else n.add(g); return n; });
  const neighbors = (n: GNode) =>
    !graphData ? [] : graphData.links.filter((l) => l.source === n.id || l.target === n.id)
      .map((l) => (l.source === n.id ? l.target : l.source)).map((id) => graphData.nodes.find((x) => x.id === id)?.label || id);
  const maxHub = Math.max(1, ...(graphData?.hubs.map((h) => h.size) || [1]));
  const auth = st.auth;
  const phase = !auth ? "loading" : !auth.checked ? "checking" : !auth.cli ? "nocli" : !auth.logged_in ? "login" : "ready";

  return (
    <main className="app flex h-screen w-screen flex-col overflow-hidden" data-state={listening ? "listening" : st.state}>
      {/* ── TOP BAR ── */}
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-line px-5">
        <div className="flex items-center gap-3">
          <span className="accent text-lg">◆</span>
          <div>
            <div className="accent text-sm font-semibold tracking-[0.34em]">A·X·O·N</div>
            <div className="text-[9px] tracking-[0.3em] text-dim">SECOND BRAIN SYSTEM</div>
          </div>
        </div>
        <div className="hidden items-center gap-4 text-right sm:flex md:gap-7">
          {[["NODES", graphData ? graphData.stats.notes.toLocaleString() : "—"],
            ["LINKS", graphData ? graphData.stats.connections.toLocaleString() : "—"],
            ["UPTIME", clock(uptime)]].map(([l, v]) => (
            <div key={l}><div className="text-[9px] tracking-[0.25em] text-dim">{l}</div><div className="accent text-sm font-semibold tabular-nums">{v}</div></div>
          ))}
          <div><div className="text-[9px] tracking-[0.25em] text-dim">STATUS</div><div className="text-sm font-semibold text-[#2bd576]">NOMINAL</div></div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* ── LEFT ── */}
        <aside className="side-bg hidden w-[260px] shrink-0 flex-col overflow-y-auto px-4 py-4 lg:flex">
          <div className="mb-3 flex items-baseline justify-between">
            <div className="accent text-xs font-semibold tracking-[0.14em]">▪ KNOWLEDGE MAP</div>
            <div className="text-[10px] text-dim">{graphData?.stats.notes ?? 0} nodes</div>
          </div>
          <input onChange={(e) => onSearch(e.target.value)} placeholder="⌕  Search the brain…"
            className="w-full rounded-md border border-line bg-[#0b1424] px-3 py-2 text-[12px] text-ink outline-none focus:border-[color:var(--accent)]" />

          {results.length > 0 && (
            <div className="mt-3">
              <div className="mb-1 text-[9px] uppercase tracking-[0.22em] text-dim">Results ({results.length}) · click to open</div>
              <div className="flex flex-col">
                {results.map((p, i) => (
                  <button key={i} onClick={() => openResult(p)} title={p} className="truncate rounded px-1.5 py-1 text-left text-[11px] text-ink hover:bg-[#12233b]">
                    {p.split(/[\\/]/).pop()}<span className="ml-1 text-[10px] text-dim">{p.replace(/[\\/][^\\/]*$/, "")}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="mb-2 mt-5 text-[9px] uppercase tracking-[0.24em] text-dim">Top hubs</div>
          {graphData?.hubs.slice(0, 7).map((h) => (
            <div key={h.label} className="mb-2.5">
              <div className="flex items-baseline justify-between text-[12px] text-ink"><span className="truncate">{h.label}</span><span className="text-dim">{h.size}</span></div>
              <div className="mt-1 w-full rounded bg-[#0e1a2b]"><div className="thinbar" style={{ width: `${(h.size / maxHub) * 100}%` }} /></div>
            </div>
          ))}

          <div className="mb-2 mt-4 text-[9px] uppercase tracking-[0.24em] text-dim">Filter by type</div>
          {graphData?.groups.filter((g) => g.name !== "core").map((g) => (
            <div key={g.name} onClick={() => toggleGroup(g.name)}
              className={"flex cursor-pointer items-center gap-2 py-1 text-[12px] " + (hidden.has(g.name) ? "opacity-30" : "")}>
              <span className="h-2.5 w-2.5 flex-none rounded-[2px]" style={{ background: colorOf(g.name) }} />
              <span className="capitalize">{g.name}</span><span className="ml-auto text-dim">{g.count}</span>
            </div>
          ))}

          <div className="mt-auto flex items-center justify-between pt-4 text-[9px] tracking-[0.2em] text-dim">
            <span>ADMIN</span><span>v2.3.0</span>
          </div>
        </aside>

        {/* ── CENTER ── */}
        <section ref={wrapRef} className="relative hidden min-w-0 flex-1 border-x border-line md:block">
          <div className="hud-grid" />
          <canvas ref={canvasRef} className="absolute inset-0" />
          <div className="graph-glow pointer-events-none absolute inset-0" />
          <div className="absolute left-4 top-4 flex items-center gap-2 rounded-full border border-line bg-[rgba(6,12,22,.7)] px-3 py-1 text-[10px] tracking-wider text-dim">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#2bd576] shadow-[0_0_8px_#2bd576]" />
            LIVE INDEX · {(st.index?.count ?? 0).toLocaleString()} FILES SCANNED
          </div>
          {selNode && !selNode.root && (
            <div className="accent-border absolute bottom-4 left-4 w-[300px] rounded-[10px] border bg-[rgba(6,12,22,.92)] p-3 text-xs leading-relaxed text-dim">
              <b className="accent text-[13px]">{selNode.label}</b>
              <button onClick={() => askAbout(selNode)} className="accent float-right text-[10px] uppercase tracking-wider">ask ▸</button>
              <br />{selNode.group} · {neighbors(selNode).length} connections<br /><br />
              <span className="break-words">{neighbors(selNode).slice(0, 24).join(", ") || "no links"}</span>
            </div>
          )}
        </section>

        {/* ── RIGHT ── */}
        <aside className="flex w-full shrink-0 flex-col bg-[rgba(6,11,20,.72)] md:w-[360px] lg:w-[400px]">
          <div style={{ height: 230, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ position: "relative", width: 200, height: 200, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg className="ticks" width={200} height={200} viewBox="0 0 200 200" style={{ position: "absolute", top: 0, left: 0 }}>
                <circle cx="100" cy="100" r="94" fill="none" stroke="var(--accent)" strokeWidth="6" strokeDasharray="1.5 8" opacity="0.6" />
              </svg>
              <svg className="ticks2" width={200} height={200} viewBox="0 0 200 200" style={{ position: "absolute", top: 0, left: 0 }}>
                <circle cx="100" cy="100" r="78" fill="none" stroke="var(--accent)" strokeWidth="3" strokeDasharray="1 11" opacity="0.35" />
              </svg>
              <div className="orb" style={{
                width: 112, height: 112, borderRadius: "50%",
                background: "radial-gradient(circle at 50% 38%, #eafcff 0%, var(--accent) 46%, #05283c 100%)",
                boxShadow: "0 0 46px 4px var(--accent), inset 0 -8px 20px rgba(0,0,0,.45)",
              }} />
            </div>
          </div>
          <div className="text-center">
            <div className="accent text-[15px] font-bold tracking-[0.34em]">{BIG[st.state] || "STANDING BY"}</div>
            <div className="mt-1 text-[11px] text-dim">{SUB[st.state] || ""}</div>
            {auth?.logged_in && auth?.reason && auth.reason !== "ok" && (
              <div className="mt-1 text-[10px] text-[#ff8a3d]" title={auth.detail}>
                {auth.reason === "rate_limited" ? "Claude may be rate-limited right now"
                  : auth.reason === "timeout" ? "Claude was slow to respond just now"
                  : "Claude had a hiccup — replies may be unreliable"}
              </div>
            )}
          </div>
          <div className="mt-3 flex justify-center gap-1.5 px-4">
            {TABS.map(([s, label]) => (
              <div key={s} className={"rounded border px-2.5 py-1 text-[9px] tracking-[0.15em] " +
                (st.state === s ? "accent-border accent" : "border-line text-dim")}>{label}</div>
            ))}
          </div>

          <div className="mt-4 flex items-center gap-2 px-4 text-[9px] uppercase tracking-[0.24em] text-dim">
            <span>▪ Transcript</span>
            <button onClick={clearChat} className="ml-auto tracking-wider hover:text-ink">clear</button>
          </div>
          <div ref={feedRef} className="feed-mask mt-2 flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-1">
            {st.history.map((m, i) => {
              const you = m.role === "user";
              return (
                <div key={i} className="anim-rise flex gap-2">
                  <div className="avatar" style={{ color: you ? "#ff8a3d" : "var(--accent)", borderColor: you ? "#3a2a1a" : undefined }}>{you ? "YOU" : "AX"}</div>
                  <div className="min-w-0 flex-1">
                    <div className="text-[9px] tracking-[0.16em] text-dim">{you ? "YOU" : "AXON"} // {clock(m.t ?? 0)}</div>
                    <div className={"mt-1 rounded-lg px-3 py-2 text-[13px] leading-relaxed " +
                      (you ? "border border-[#3a2a1a] bg-[#1a130a] text-[#f2dcc0]" : "msg-axon text-ink")}>{m.text}</div>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mx-3 mb-1 flex items-center gap-2">
            <select value={voiceLang} onChange={(e) => setVoiceLang(e.target.value)}
              title="Voice recognition language"
              className="rounded-md border border-line bg-[#0b1424] px-1.5 py-1 text-[10px] text-dim outline-none">
              <option value="en-US">EN-US</option>
              <option value="en-GB">EN-UK</option>
              <option value="hi-IN">Hindi</option>
              <option value="es-ES">Español</option>
              <option value="fr-FR">Français</option>
              <option value="de-DE">Deutsch</option>
              <option value="ja-JP">日本語</option>
              <option value="zh-CN">中文</option>
            </select>
            <button onClick={toggleWakeMode} title={wakeMode ? "Stop always-listening" : "Always listen for 'Hey Axon'"}
              className={"rounded-md border px-2 py-1 text-[10px] uppercase tracking-wider transition " +
                (wakeMode ? "border-transparent bg-[#2bd576] text-[#04121a]" : "accent-border text-dim")}>
              🎧 {wakeMode ? "wake word on" : "wake word off"}
            </button>
          </div>

          <div className="glow m-3 flex items-center gap-2 rounded-xl border accent-border bg-panel py-2 pl-3 pr-2">
            <span className="accent whitespace-nowrap rounded-full border accent-border px-2 py-0.5 text-[10px] uppercase tracking-wider">
              {(st.model || "model").replace(/^claude-/, "").toUpperCase()}
            </span>
            <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder={wakeMode ? "Say 'Axon' then your command…" : listening ? "Listening… speak now" : "Speak, or type a command…"} autoFocus
              className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-dim" />
            <button onClick={toggleMic} disabled={wakeMode} title={wakeMode ? "Wake-word mode is listening" : listening ? "Stop listening" : "Talk to Axon"}
              className={"grid h-9 w-9 shrink-0 place-items-center rounded-lg border transition disabled:opacity-40 " +
                (listening ? "border-transparent bg-[#ff5470] text-white animate-pulse" : "accent-border accent")}>🎤</button>
            <button onClick={send} title="Send" className="send-btn grid h-9 w-9 shrink-0 place-items-center rounded-lg text-[#04121a] transition active:scale-90">➤</button>
          </div>
          <div className="pb-2 text-center text-[10px] text-dim">
            {wakeMode ? "🎧 always listening — say \"Axon\" then your command" : "🎤 click the mic and speak · allow the browser mic prompt once"}
          </div>
        </aside>
      </div>

      {phase !== "ready" && (
        <div style={{ position: "fixed", inset: 0, zIndex: 9999, background: "#04070d",
                      display: "grid", placeItems: "center" }}>
          <div className="hud-grid" style={{ opacity: 0.4 }} />
          <div className="accent-border relative w-[440px] rounded-2xl border bg-[rgba(8,14,24,.95)] p-8 text-center">
            <div className="accent text-xl font-semibold tracking-[0.34em]">◆ A·X·O·N</div>
            <div className="mt-1 text-[10px] tracking-[0.3em] text-dim">SECOND BRAIN SYSTEM</div>
            {(phase === "loading" || phase === "checking") && (
              <div className="mt-8 text-sm text-dim">Checking sign-in…</div>
            )}
            {phase === "nocli" && (
              <>
                <div className="mt-7 text-sm text-ink">Claude Code isn&apos;t installed on this PC.</div>
                <div className="mt-2 text-xs leading-relaxed text-dim">
                  Run <span className="accent">setup.ps1</span> once (it installs Claude Code + dependencies), then reopen AXON.
                </div>
                <button onClick={recheck} className="send-btn mt-6 rounded-lg px-5 py-2 text-sm text-[#04121a]">Re-check</button>
              </>
            )}
            {phase === "login" && (
              <>
                <div className="mt-7 text-sm text-ink">Sign in to Claude to activate AXON.</div>
                <div className="mt-4 space-y-1.5 text-left text-xs leading-relaxed text-dim">
                  <div><b className="accent">1.</b> Click <b className="accent">Open sign-in</b> — a small window opens.</div>
                  <div><b className="accent">2.</b> In it, type <b className="accent">/login</b> and sign in with your Claude account in the browser.</div>
                  <div><b className="accent">3.</b> Come back here and click <b className="accent">I&apos;ve signed in</b>.</div>
                </div>
                <div className="mt-6 flex gap-2">
                  <button onClick={signIn} className="accent accent-border flex-1 rounded-lg border py-2 text-sm">Open sign-in</button>
                  <button onClick={recheck} disabled={rechecking} className="send-btn flex-1 rounded-lg py-2 text-sm text-[#04121a] disabled:opacity-60">
                    {rechecking ? "Verifying…" : "I've signed in"}
                  </button>
                </div>
                <div className="mt-4 text-[10px] text-dim">Uses your Claude subscription — no API key, no extra cost.</div>
              </>
            )}
          </div>
        </div>
      )}
    </main>
  );
}
