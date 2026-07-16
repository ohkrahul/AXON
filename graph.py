"""Build a force-graph of a markdown notes folder — AXON's 'second brain'.

Nodes are notes; edges are [[wiki links]] (or markdown .md links) between them.
Each note may declare `group: <name>` on its first lines to colour-code it.
If the notes folder is empty, a small interlinked starter set is seeded so the
graph is never blank.
"""
from __future__ import annotations

import re
from pathlib import Path

import config

_WIKILINK = re.compile(r"\[\[([^\]|#]+)")
_MDLINK = re.compile(r"\]\(([^)]+?\.md)\)")
_GROUP = re.compile(r"^group:\s*([A-Za-z0-9_-]+)", re.MULTILINE)

# Starter "second brain" — themed around this project so the graph is coherent.
_SEED: dict[str, str] = {
    "AXON": "group: core\n\nThe assistant itself. Connects to [[Second Brain]], "
            "[[Claude]], [[Voice Control]] and lives inside [[Graphify]].",
    "Graphify": "group: project\n\nThe product. Builds on [[AXON]], [[Graph View]] "
                "and the [[Knowledge Graph]] idea.",
    "Second Brain": "group: concept\n\nA linked web of [[Notes]] you can explore as "
                    "a [[Graph View]]. Powers [[AXON]].",
    "Knowledge Graph": "group: concept\n\nNodes and edges over your [[Notes]]. See "
                       "[[Graph View]] and [[Second Brain]].",
    "Graph View": "group: concept\n\nThe interactive map of the [[Knowledge Graph]] "
                  "and [[Second Brain]], shipped in [[Graphify]].",
    "Notes": "group: concept\n\nAtomic notes that link together to form the "
             "[[Second Brain]] and [[Knowledge Graph]].",
    "Claude": "group: tool\n\nThe brain behind [[AXON]], driven via the [[Agent SDK]].",
    "Agent SDK": "group: tool\n\nLets [[Claude]] use [[Tools]] and power [[AXON]].",
    "Tools": "group: tool\n\nActions [[AXON]] can take, exposed through the [[Agent SDK]].",
    "Voice Control": "group: skill\n\nHands-free [[AXON]] via [[Wake Word]], "
                     "[[Speech To Text]] and [[Text To Speech]].",
    "Wake Word": "group: skill\n\nThe phrase that activates [[Voice Control]].",
    "Speech To Text": "group: skill\n\nTurns your voice into text for [[Voice Control]].",
    "Text To Speech": "group: skill\n\nGives [[AXON]] a voice for [[Voice Control]].",
}


def _seed(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for title, body in _SEED.items():
        p = folder / f"{title}.md"
        if not p.exists():
            p.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")


def build_graph(folder: str | None = None) -> dict:
    root = Path(folder or config.NOTES_DIR)
    md = list(root.glob("*.md")) if root.exists() else []
    if not md:
        _seed(root)
        md = list(root.glob("*.md"))

    nodes, ids, deg, groups = [], set(), {}, {}
    text_by_id = {}
    for p in md:
        nid = p.stem.lower()
        ids.add(nid)
        text_by_id[nid] = (p.stem, p.read_text(encoding="utf-8", errors="ignore"))

    for nid, (label, text) in text_by_id.items():
        g = (_GROUP.search(text) or [None, "note"])
        group = g[1] if isinstance(g, list) else (g.group(1) if g else "note")
        groups[group] = groups.get(group, 0) + 1
        nodes.append({"id": nid, "label": label, "group": group, "size": 1})
        deg[nid] = 0

    links = []
    seen = set()
    for nid, (_label, text) in text_by_id.items():
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

    return {
        "title": root.name.upper() + " · SECOND BRAIN",
        "nodes": nodes,
        "links": links,
        "groups": [{"name": k, "count": v} for k, v in sorted(groups.items())],
        "hubs": [{"label": h["label"], "size": h["size"]} for h in hubs],
        "stats": {"notes": len(nodes), "connections": len(links)},
    }
