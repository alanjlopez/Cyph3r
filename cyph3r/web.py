"""Static HTML for the interactive graph viewer.

A self-contained page that fetches ``/graph`` from the same origin and renders it with
vis-network (loaded from a CDN). Kept as a plain string so the API can serve it with no
templating engine or static-file machinery.
"""

VIEW_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Cyph3r — Graph Viewer</title>
  <script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; font-family: system-ui, sans-serif; background: #14161a; color: #e6e6e6; }
    #bar {
      display: flex; align-items: center; gap: 12px;
      padding: 10px 14px; background: #1d2026; border-bottom: 1px solid #2c2f36;
    }
    #bar b { color: #79c0ff; }
    #bar input { width: 90px; padding: 4px 6px; background: #0d1117; color: #e6e6e6;
      border: 1px solid #30363d; border-radius: 6px; }
    #bar button { padding: 5px 12px; background: #238636; color: #fff; border: none;
      border-radius: 6px; cursor: pointer; }
    #bar button:hover { background: #2ea043; }
    #counts { margin-left: auto; color: #8b949e; font-size: 13px; }
    #banner { display: none; padding: 8px 14px; background: #5a3a00; color: #ffd591;
      font-size: 13px; }
    #net { width: 100vw; height: calc(100vh - 52px); }
    #err { color: #ff7b72; padding: 0 14px; }
  </style>
</head>
<body>
  <div id="bar">
    <b>Cyph3r</b> graph viewer
    <label>nodes:&nbsp;<input id="limit" type="number" min="1" max="2000" value="300" /></label>
    <label><input id="meta" type="checkbox" /> include memory</label>
    <button id="reload">Reload</button>
    <span id="err"></span>
    <span id="counts"></span>
  </div>
  <div id="banner"></div>
  <div id="net"></div>
  <script>
    const palette = ["#79c0ff","#56d364","#ffa657","#d2a8ff","#ff7b72","#f2cc60",
                     "#7ee787","#ffa198","#a5d6ff","#e3b341"];
    const colorByLabel = {};
    function colorFor(label) {
      if (!(label in colorByLabel))
        colorByLabel[label] = palette[Object.keys(colorByLabel).length % palette.length];
      return colorByLabel[label];
    }
    function caption(props) {
      return props.name || props.title || props.id || "";
    }
    function tooltip(labels, props) {
      const head = labels.length ? ":" + labels.join(":") : "(node)";
      const body = Object.entries(props).map(([k, v]) => `${k}: ${v}`).join("\\n");
      return body ? `${head}\\n${body}` : head;
    }
    async function load() {
      const limit = document.getElementById("limit").value || 300;
      const meta = document.getElementById("meta").checked;
      const err = document.getElementById("err");
      err.textContent = "";
      let data;
      try {
        const resp = await fetch(`/graph?limit=${limit}&include_meta=${meta}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        data = await resp.json();
      } catch (e) {
        err.textContent = "Failed to load /graph: " + e.message;
        return;
      }
      const nodes = data.nodes.map(n => {
        const label = (n.labels && n.labels[0]) || "Node";
        return {
          id: n.id,
          label: caption(n.properties) || label,
          group: label,
          color: colorFor(label),
          title: tooltip(n.labels || [], n.properties || {}),
        };
      });
      const edges = data.edges.map(e => ({
        id: e.id, from: e.source, to: e.target, label: e.type, arrows: "to",
        font: { color: "#8b949e", size: 10, strokeWidth: 0 }, color: { color: "#586069" },
      }));
      const c = data.counts || {};
      document.getElementById("counts").textContent =
        `${c.nodes_shown ?? nodes.length} / ${c.nodes_total ?? "?"} nodes · ${c.edges_shown ?? edges.length} edges`;
      const banner = document.getElementById("banner");
      if (data.truncated) {
        banner.style.display = "block";
        banner.textContent =
          `Showing ${c.nodes_shown} of ${c.nodes_total} nodes — raise the node limit to see more.`;
      } else {
        banner.style.display = "none";
      }
      new vis.Network(
        document.getElementById("net"),
        { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) },
        {
          nodes: { shape: "dot", size: 16, font: { color: "#e6e6e6" } },
          physics: { stabilization: true, barnesHut: { gravitationalConstant: -8000 } },
          interaction: { hover: true, tooltipDelay: 120 },
        }
      );
    }
    document.getElementById("reload").addEventListener("click", load);
    load();
  </script>
</body>
</html>
"""
