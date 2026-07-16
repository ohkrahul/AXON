"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Msg = { role: "user" | "axon"; text: string };
type St = { state: string; model: string; mic: boolean; history: Msg[] };
type GNode = { id: string; label: string; group: string; size: number };
type GLink = { source: string; target: string };
type Graph = {
  title: string;
  nodes: GNode[];
  links: GLink[];
  groups: { name: string; count: number }[];
  hubs: { label: string; size: number }[];
  stats: { notes: number; connections: number };
};

const SUBS: Record<string, string> = {
  idle: "standing by, sir",
  listening: "listening, sir…",
  thinking: "processing your request…",
  speaking: "speaking…",
  error: "something went wrong",
};
const GC: Record<string, string> = {
  core: "#ff8a3d", project: "#b06cff", concept: "#ffd23f",
  skill: "#21d4fd", tool: "#2bd576", note: "#6b7fa0",
};
const colorOf = (g: string) => GC[g] || "#6b7fa0";

export default function Home() {
  const [st, setSt] = useState<St>({ state: "idle", model: "", mic: false, history: [] });
  const [text, setText] = useState("");
  const [brainOpen, setBrainOpen] = useState(false);
  const [graphData, setGraphData] = useState<Graph | null>(null);
  const [graphLoaded, setGraphLoaded] = useState(0);
  const [selNode, setSelNode] = useState<GNode | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  const feedRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const graphRef = useRef<any>(null);
  const selRef = useRef<GNode | null>(null);
  const hiddenRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch("/api/state", { cache: "no-store" });
        const data = (await r.json()) as St;
        if (alive) setSt(data);
      } catch {}
    };
    tick();
    const id = setInterval(tick, 250);
    return () => { alive = false; clearInterval(id); };
  }, []);

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [st.history.length]);

  useEffect(() => { selRef.current = selNode; }, [selNode]);
  useEffect(() => { hiddenRef.current = hidden; }, [hidden]);

  const send = useCallback(async () => {
    const t = text.trim();
    if (!t) return;
    setText("");
    try {
      await fetch("/api/say", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: t }),
      });
    } catch {}
  }, [text]);

  const openBrain = useCallback(async () => {
    setBrainOpen(true);
    if (!graphRef.current) {
      const g = (await (await fetch("/api/graph")).json()) as Graph;
      const cx = window.innerWidth / 2, cy = window.innerHeight / 2;
      (g.nodes as any[]).forEach((n, i) => {
        const a = i * 2.4;
        n.x = cx + Math.cos(a) * (120 + (i % 4) * 70);
        n.y = cy + Math.sin(a) * (110 + (i % 3) * 70);
        n.vx = 0; n.vy = 0;
      });
      const byId: Record<string, any> = {};
      (g.nodes as any[]).forEach((n) => (byId[n.id] = n));
      (g as any).byId = byId;
      graphRef.current = g;
      setGraphData(g);
      setGraphLoaded((x) => x + 1);
    }
  }, []);

  useEffect(() => {
    if (!brainOpen) return;
    const G = graphRef.current;
    const canvas = canvasRef.current;
    if (!G || !canvas) return;
    const ctx = canvas.getContext("2d")!;
    let cw = 0, ch = 0;
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      cw = window.innerWidth; ch = window.innerHeight;
      canvas.width = Math.floor(cw * dpr);
      canvas.height = Math.floor(ch * dpr);
      canvas.style.width = cw + "px";
      canvas.style.height = ch + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    let drag: any = null, hover: any = null, raf = 0;
    const vis = (n: any) => !hiddenRef.current.has(n.group);
    const isNbr = (a: any, b: any) =>
      G.links.some((l: GLink) => (l.source === a.id && l.target === b.id) || (l.target === a.id && l.source === b.id));

    const step = () => {
      const cx = cw / 2 + 130, cy = ch / 2, REP = 2200, SPRING = 0.02, LEN = 96, DAMP = 0.85;
      for (const n of G.nodes) { n.fx = (cx - n.x) * 0.004; n.fy = (cy - n.y) * 0.004; }
      for (let i = 0; i < G.nodes.length; i++)
        for (let j = i + 1; j < G.nodes.length; j++) {
          const a = G.nodes[i], b = G.nodes[j];
          const dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy || 1, d = Math.sqrt(d2), f = REP / d2;
          const ux = dx / d, uy = dy / d; a.fx += ux * f; a.fy += uy * f; b.fx -= ux * f; b.fy -= uy * f;
        }
      for (const l of G.links as GLink[]) {
        const a = G.byId[l.source], b = G.byId[l.target];
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1, f = SPRING * (d - LEN);
        const ux = dx / d, uy = dy / d; a.fx += ux * f; a.fy += uy * f; b.fx -= ux * f; b.fy -= uy * f;
      }
      for (const n of G.nodes) { if (n === drag) continue; n.vx = (n.vx + n.fx) * DAMP; n.vy = (n.vy + n.fy) * DAMP; n.x += n.vx; n.y += n.vy; }
    };
    const draw = () => {
      const sel = selRef.current as any;
      ctx.clearRect(0, 0, cw, ch);
      for (const l of G.links as GLink[]) {
        const a = G.byId[l.source], b = G.byId[l.target];
        if (!vis(a) || !vis(b)) continue;
        const hot = sel && (l.source === sel.id || l.target === sel.id);
        ctx.strokeStyle = hot ? "rgba(130,205,255,.75)" : "rgba(80,140,200,.14)";
        ctx.lineWidth = hot ? 1.6 : 0.8;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      }
      for (const n of G.nodes) {
        if (!vis(n)) continue;
        const r = 6 + n.size * 1.7;
        const dim = sel && sel.id !== n.id && !isNbr(sel, n);
        ctx.globalAlpha = dim ? 0.22 : 1; ctx.fillStyle = colorOf(n.group);
        ctx.shadowColor = colorOf(n.group); ctx.shadowBlur = n === hover || (sel && sel.id === n.id) ? 20 : 8;
        ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
        if (n === hover || (sel && sel.id === n.id) || n.size >= 4) {
          ctx.globalAlpha = dim ? 0.3 : 0.95; ctx.fillStyle = "#dcebff";
          ctx.font = "11px Segoe UI"; ctx.textAlign = "center"; ctx.fillText(n.label, n.x, n.y - r - 6);
        }
        ctx.globalAlpha = 1;
      }
    };
    const loop = () => { step(); draw(); raf = requestAnimationFrame(loop); };
    loop();

    const at = (x: number, y: number) => {
      for (let i = G.nodes.length - 1; i >= 0; i--) {
        const n = G.nodes[i]; if (!vis(n)) continue;
        const r = 6 + n.size * 1.7;
        if ((x - n.x) ** 2 + (y - n.y) ** 2 <= (r + 5) ** 2) return n;
      }
      return null;
    };
    const onMove = (e: MouseEvent) => {
      const b = canvas.getBoundingClientRect(), x = e.clientX - b.left, y = e.clientY - b.top;
      if (drag) { drag.x = x; drag.y = y; drag.vx = 0; drag.vy = 0; }
      else { hover = at(x, y); canvas.style.cursor = hover ? "pointer" : "default"; }
    };
    const onDown = (e: MouseEvent) => {
      const b = canvas.getBoundingClientRect(), n = at(e.clientX - b.left, e.clientY - b.top);
      if (n) { drag = n; setSelNode(n); } else setSelNode(null);
    };
    const onUp = () => { drag = null; };
    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mousedown", onDown);
    window.addEventListener("mouseup", onUp);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("mouseup", onUp);
      canvas.removeEventListener("mousemove", onMove);
      canvas.removeEventListener("mousedown", onDown);
    };
  }, [brainOpen, graphLoaded]);

  const toggleGroup = (g: string) =>
    setHidden((h) => { const n = new Set(h); if (n.has(g)) n.delete(g); else n.add(g); return n; });

  const onSearch = (q: string) => {
    q = q.trim().toLowerCase();
    if (!q || !graphData) { setSelNode(null); return; }
    const hit = graphData.nodes.find((n) => n.label.toLowerCase().includes(q));
    if (hit) setSelNode(hit);
  };

  const neighbors = (n: GNode) => {
    if (!graphData) return [];
    return graphData.links
      .filter((l) => l.source === n.id || l.target === n.id)
      .map((l) => (l.source === n.id ? l.target : l.source))
      .map((id) => graphData.nodes.find((x) => x.id === id)?.label || id);
  };

  return (
    <main className="app relative flex h-screen flex-col items-center" data-state={st.state}>
      <div className="grid" />
      <div className="corner tl" /><div className="corner tr" />
      <div className="corner bl" /><div className="corner br" />

      <header className="mt-6 text-center text-xs uppercase tracking-[0.42em] text-dim">
        ◆ <b className="accent">A.X.O.N.</b> • Second Brain ◆
      </header>

      <div className="reactor my-3">
        <svg className="ticks" viewBox="0 0 300 300"><circle cx="150" cy="150" r="140" fill="none" stroke="var(--accent)" strokeWidth="8" strokeDasharray="1.5 9" opacity=".55" /></svg>
        <svg className="ticks2" viewBox="0 0 232 232"><circle cx="116" cy="116" r="108" fill="none" stroke="var(--accent)" strokeWidth="5" strokeDasharray="1 12" opacity=".4" /></svg>
        <svg className="sweep" viewBox="0 0 300 300"><circle cx="150" cy="150" r="118" fill="none" stroke="var(--amber)" strokeWidth="3" strokeDasharray="150 600" strokeLinecap="round" opacity=".85" /></svg>
        <div className="ring r1" /><div className="ring r2" /><div className="ring r3" />
        <div className="core"><span className="text-[13px] font-extrabold tracking-[0.12em] text-[#02121a]">AXON</span></div>
      </div>

      <div className="text-center">
        <div className="accent text-[15px] font-bold tracking-[0.34em]">
          <span className="dot mr-2 inline-block h-2 w-2 rounded-full align-middle bg-[var(--accent)] shadow-[0_0_10px_var(--accent)]" />
          {st.state.toUpperCase()}
        </div>
        <div className="mt-1 min-h-4 text-xs text-dim">{SUBS[st.state] || ""}</div>
      </div>

      <div ref={feedRef} className="feed-mask my-3.5 flex w-[min(760px,92vw)] flex-1 flex-col gap-2.5 overflow-y-auto px-1.5">
        {st.history.map((m, i) => (
          <div
            key={i}
            className={
              "anim-rise max-w-[80%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed " +
              (m.role === "user"
                ? "self-end border border-[#1d3f63] bg-[#0e2036] text-[#dcecff]"
                : "msg-axon self-start text-ink")
            }
          >
            <div className="mb-1 text-[10px] uppercase tracking-[0.18em] text-dim">{m.role === "user" ? "You" : "Axon"}</div>
            {m.text}
          </div>
        ))}
      </div>

      <div className="glow mb-5 flex w-[min(760px,92vw)] items-center gap-2.5 rounded-2xl border accent-border bg-panel py-2 pl-4 pr-2">
        <span className="accent whitespace-nowrap rounded-full border accent-border px-2.5 py-1 text-[11px] uppercase tracking-wider">
          {(st.model || "model").replace(/^claude-/, "").toUpperCase()}
        </span>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Speak to Axon… (type a command)"
          autoFocus
          className="flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-dim"
        />
        <button onClick={send} title="Send" className="send-btn grid h-[42px] w-[42px] place-items-center rounded-[10px] text-lg text-[#04121a] transition active:scale-90">➤</button>
        <span className="whitespace-nowrap text-[11px] tracking-wide text-dim">{st.mic ? "🎙 voice on" : "⌨ type to talk"}</span>
      </div>

      <button onClick={openBrain} className="accent accent-border fixed right-[78px] top-4 z-[6] rounded-lg border bg-panel px-3 py-1.5 text-[11px] uppercase tracking-[0.14em]">▣ Brain</button>

      {brainOpen && (
        <div className="brain-bg fixed inset-0 z-20">
          <canvas ref={canvasRef} className="absolute inset-0" />
          <div className="side-bg absolute left-0 top-0 h-full w-[272px] overflow-y-auto border-r border-line px-[18px] py-[22px]">
            <h2 className="accent text-[13px] tracking-[0.16em]">{graphData?.title || "SECOND BRAIN"}</h2>
            <div className="mb-3.5 mt-1 text-[11px] text-dim">
              {graphData ? `${graphData.stats.notes} notes · ${graphData.stats.connections} connections` : "loading…"}
            </div>
            <input onChange={(e) => onSearch(e.target.value)} placeholder="Search the brain…" className="w-full rounded-lg border border-line bg-[#0b1424] px-2.5 py-2 text-[13px] text-ink outline-none" />
            <div className="mb-1.5 mt-4 text-[10px] uppercase tracking-[0.2em] text-dim">Top hubs</div>
            {graphData?.hubs.map((h) => (
              <div key={h.label} className="flex items-center gap-2 px-0.5 py-1 text-xs"><span>{h.label}</span><span className="ml-auto text-dim">{h.size}</span></div>
            ))}
            <div className="mb-1.5 mt-4 text-[10px] uppercase tracking-[0.2em] text-dim">Filter</div>
            {graphData?.groups.map((g) => (
              <div
                key={g.name}
                onClick={() => toggleGroup(g.name)}
                className={"flex cursor-pointer items-center gap-2 px-0.5 py-1 text-xs " + (hidden.has(g.name) ? "opacity-30" : "")}
              >
                <span className="h-2.5 w-2.5 flex-none rounded-full" style={{ background: colorOf(g.name) }} />
                {g.name}
                <span className="ml-auto text-dim">{g.count}</span>
              </div>
            ))}
          </div>
          <button onClick={() => setBrainOpen(false)} className="fixed right-4 top-4 z-[22] rounded-lg border border-line bg-panel px-3 py-1.5 text-ink">✕ Close</button>
          {selNode && (
            <div className="accent-border absolute bottom-4 right-4 w-[264px] rounded-[10px] border bg-[rgba(6,12,22,.92)] p-3 text-xs leading-relaxed text-dim">
              <b className="accent text-[13px]">{selNode.label}</b><br />
              {selNode.group} · {neighbors(selNode).length} connections<br /><br />
              {neighbors(selNode).join(", ") || "no links yet"}
            </div>
          )}
        </div>
      )}
    </main>
  );
}
