"""Build the force-graph for AXON's 'second brain'.

Two sources:
  • Real file map (default): walk an actual folder tree on the PC — files and
    folders become nodes, containment becomes edges, grouped by file type. This
    is what fills the graph with ALL your data (config.GRAPH_ROOT).
  • Notes vault (fallback): a folder of markdown notes linked by [[wiki links]]
    (config.NOTES_DIR), seeded on first run so it's never empty.
"""
from __future__ import annotations

import os
import re
from collections import deque
from pathlib import Path

import config

# ── file categories (drive node colour) ──────────────────────────────────
_CATS = {
    "document": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".ppt",
                 ".pptx", ".xls", ".xlsx", ".csv", ".epub"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".ico", ".heic"},
    "video": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".flv"},
    "audio": {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"},
    "code": {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".cs",
             ".go", ".rs", ".rb", ".php", ".html", ".css", ".json", ".sh",
             ".ps1", ".bat", ".ipynb", ".sql", ".yml", ".yaml"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".iso"},
}
_EXCLUDE = {"node_modules", ".git", ".next", ".venv", "__pycache__", ".cache",
            "$recycle.bin", "appdata", "application data", "onedrivetemp",
            ".vscode", ".idea", "site-packages", ".gradle", ".m2"}


def _category(name: str, is_dir: bool) -> str:
    if is_dir:
        return "folder"
    ext = os.path.splitext(name)[1].lower()
    for cat, exts in _CATS.items():
        if ext in exts:
            return cat
    return "file"


# ── real file-tree graph ─────────────────────────────────────────────────
def _tree_graph(root: str) -> dict:
    root = os.path.abspath(root)
    nodes: list[dict] = []
    links: list[dict] = []
    ids: set[str] = set()
    children: dict[str, int] = {}

    def add(path: str, label: str, group: str) -> None:
        nodes.append({"id": path, "label": label, "group": group, "size": 1, "hub": False})
        ids.add(path)
        children[path] = 0

    add(root, os.path.basename(root.rstrip("\\/")) or root, "folder")
    q: deque[tuple[str, int]] = deque([(root, 0)])
    MAX, DEPTH = config.GRAPH_MAX_NODES, config.GRAPH_MAX_DEPTH

    while q and len(nodes) < MAX:
        d, depth = q.popleft()
        if depth >= DEPTH:
            continue
        try:
            entries = list(os.scandir(d))
        except (PermissionError, OSError):
            continue
        entries.sort(key=lambda e: (not _safe_isdir(e), e.name.lower()))
        for e in entries:
            if len(nodes) >= MAX:
                break
            nm = e.name
            if nm.startswith(".") or nm.lower() in _EXCLUDE:
                continue
            is_dir = _safe_isdir(e)
            p = e.path
            if p in ids:
                continue
            add(p, nm, _category(nm, is_dir))
            links.append({"source": d, "target": p})
            children[d] = children.get(d, 0) + 1
            if is_dir:
                q.append((p, depth + 1))

    groups: dict[str, int] = {}
    for n in nodes:
        c = children.get(n["id"], 0)
        n["size"] = min(1 + c, 14) if n["group"] == "folder" else 1
        groups[n["group"]] = groups.get(n["group"], 0) + 1
    hubs = sorted(nodes, key=lambda n: -n["size"])[:14]
    for h in hubs:
        h["hub"] = True

    name = os.path.basename(root.rstrip("\\/")) or root
    return {
        "title": name.upper() + " · FILE MAP",
        "nodes": nodes,
        "links": links,
        "groups": [{"name": k, "count": v} for k, v in sorted(groups.items())],
        "hubs": [{"label": h["label"], "size": h["size"]} for h in hubs],
        "stats": {"notes": len(nodes), "connections": len(links)},
    }


def _safe_isdir(entry) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return False


# ── notes-vault graph (fallback) ─────────────────────────────────────────
_WIKILINK = re.compile(r"\[\[([^\]|#]+)")
_MDLINK = re.compile(r"\]\(([^)]+?\.md)\)")
_GROUP = re.compile(r"^group:\s*([A-Za-z0-9_-]+)", re.MULTILINE)
_SEED = {
    "AXON": "group: core\n\nConnects [[Second Brain]], [[Claude]], [[Voice Control]], [[Graphify]].",
    "Graphify": "group: project\n\nBuilds on [[AXON]], [[Graph View]], [[Knowledge Graph]].",
    "Second Brain": "group: concept\n\nLinked [[Notes]] shown as a [[Graph View]]. Powers [[AXON]].",
    "Knowledge Graph": "group: concept\n\nNodes/edges over [[Notes]]. See [[Graph View]], [[Second Brain]].",
    "Graph View": "group: concept\n\nMap of the [[Knowledge Graph]] and [[Second Brain]] in [[Graphify]].",
    "Notes": "group: concept\n\nAtomic notes forming the [[Second Brain]] and [[Knowledge Graph]].",
    "Claude": "group: tool\n\nThe brain behind [[AXON]], via the [[Agent SDK]].",
    "Agent SDK": "group: tool\n\nLets [[Claude]] use [[Tools]] and power [[AXON]].",
    "Tools": "group: tool\n\nActions [[AXON]] can take through the [[Agent SDK]].",
    "Voice Control": "group: skill\n\nHands-free [[AXON]] via [[Wake Word]], [[Speech To Text]], [[Text To Speech]].",
    "Wake Word": "group: skill\n\nThe phrase that activates [[Voice Control]].",
    "Speech To Text": "group: skill\n\nTurns your voice into text for [[Voice Control]].",
    "Text To Speech": "group: skill\n\nGives [[AXON]] a voice for [[Voice Control]].",
}


def _notes_graph() -> dict:
    root = Path(config.NOTES_DIR)
    md = list(root.glob("*.md")) if root.exists() else []
    if not md:
        root.mkdir(parents=True, exist_ok=True)
        for title, body in _SEED.items():
            (root / f"{title}.md").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        md = list(root.glob("*.md"))

    text_by_id, deg, groups = {}, {}, {}
    for p in md:
        text_by_id[p.stem.lower()] = (p.stem, p.read_text(encoding="utf-8", errors="ignore"))
    ids = set(text_by_id)
    nodes = []
    for nid, (label, text) in text_by_id.items():
        m = _GROUP.search(text)
        group = m.group(1) if m else "note"
        groups[group] = groups.get(group, 0) + 1
        nodes.append({"id": nid, "label": label, "group": group, "size": 1, "hub": False})
        deg[nid] = 0
    links, seen = [], set()
    for nid, (_l, text) in text_by_id.items():
        targets = {t.strip().lower() for t in _WIKILINK.findall(text)}
        targets |= {Path(m).stem.lower() for m in _MDLINK.findall(text)}
        for t in targets:
            if t in ids and t != nid and (nid, t) not in seen and (t, nid) not in seen:
                seen.add((nid, t))
                links.append({"source": nid, "target": t})
                deg[nid] += 1
                deg[t] += 1
    for n in nodes:
        n["size"] = 1 + deg[n["id"]]
    hubs = sorted(nodes, key=lambda n: -n["size"])[:8]
    for h in hubs:
        h["hub"] = True
    return {
        "title": root.name.upper() + " · SECOND BRAIN",
        "nodes": nodes, "links": links,
        "groups": [{"name": k, "count": v} for k, v in sorted(groups.items())],
        "hubs": [{"label": h["label"], "size": h["size"]} for h in hubs],
        "stats": {"notes": len(nodes), "connections": len(links)},
    }


def build_graph(folder: str | None = None) -> dict:
    root = folder or config.GRAPH_ROOT
    if root:
        root = os.path.expanduser(root)
        if os.path.isdir(root):
            return _tree_graph(root)
    return _notes_graph()
