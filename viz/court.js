// SwingVision coordinates (metres):
//   x=0 centre service line, x<0 deuce box, x>0 ad box
//   y=0 server's baseline, y≈11.885 net, y≈18.285 far service line

const NET_Y  = 11.885;
const SVC_Y  = 18.285;
const HALF_X = 4.115;

const ASPECT = (HALF_X * 2) / (SVC_Y - NET_Y); // ≈ 1.29

function makeCourt(svgId, densityColor) {
  const svg = d3.select(`#${svgId}`);
  const width = svg.node().getBoundingClientRect().width || 380;
  const PAD = 6;
  const innerW = width - PAD * 2;
  const innerH = Math.round(innerW / ASPECT);

  svg.attr("viewBox", `0 0 ${width} ${innerH + PAD * 2}`);

  const g = svg.append("g").attr("transform", `translate(${PAD},${PAD})`);
  const xS = d3.scaleLinear().domain([-HALF_X, HALF_X]).range([0, innerW]);
  const yS = d3.scaleLinear().domain([NET_Y, SVC_Y]).range([0, innerH]);

  g.append("rect")
    .attr("width", innerW).attr("height", innerH)
    .attr("fill", "#1a3a28")
    .attr("rx", 2);

  // faint T-zone hints
  const tWidth = xS(1.4) - xS(0);
  [[xS(-1.4), tWidth], [xS(0), tWidth]].forEach(([x, w]) =>
    g.append("rect").attr("x", x).attr("y", 0).attr("width", w).attr("height", innerH)
      .attr("fill", "rgba(255,255,255,0.025)")
  );

  const mkLine = (x1, y1, x2, y2, isNet) =>
    g.append("line")
      .attr("x1", xS(x1)).attr("y1", yS(y1)).attr("x2", xS(x2)).attr("y2", yS(y2))
      .attr("stroke", isNet ? "rgba(255,255,255,0.85)" : "rgba(255,255,255,0.55)")
      .attr("stroke-width", isNet ? 2.5 : 1.5)
      .attr("stroke-linecap", "round");

  mkLine(-HALF_X, NET_Y, HALF_X, NET_Y, true);
  mkLine(-HALF_X, SVC_Y, HALF_X, SVC_Y, false);
  mkLine(-HALF_X, NET_Y, -HALF_X, SVC_Y, false);
  mkLine(HALF_X, NET_Y, HALF_X, SVC_Y, false);
  mkLine(0, NET_Y, 0, SVC_Y, false);

  const textStyle = (sel, opacity = 0.28) =>
    sel.attr("text-anchor", "middle")
       .attr("fill", `rgba(255,255,255,${opacity})`)
       .attr("font-size", 8.5)
       .attr("font-family", "-apple-system, BlinkMacSystemFont, sans-serif")
       .attr("letter-spacing", "0.07em");

  const labelY = yS(SVC_Y) - 7;
  textStyle(g.append("text").attr("x", xS(-3.2)).attr("y", labelY)).text("WIDE");
  textStyle(g.append("text").attr("x", xS(-0.7)).attr("y", labelY)).text("T");
  textStyle(g.append("text").attr("x", xS(0.7)).attr("y", labelY)).text("T");
  textStyle(g.append("text").attr("x", xS(3.2)).attr("y", labelY)).text("WIDE");
  textStyle(g.append("text").attr("x", innerW / 2).attr("y", yS(NET_Y) + 10), 0.22).text("NET");

  const contourLayer = g.append("g");
  const dotLayer = g.append("g");
  const emptyLabel = g.append("text")
    .attr("x", innerW / 2).attr("y", innerH / 2)
    .attr("text-anchor", "middle")
    .attr("font-size", 11).attr("font-family", "-apple-system, BlinkMacSystemFont, sans-serif")
    .attr("fill", "rgba(255,255,255,0.2)");

  const colorScale = d3.scaleSequential()
    .interpolator(d3.interpolateRgb("rgba(0,0,0,0)", densityColor));

  function update(points) {
    const inPlay = points.filter(d => d.result === "in");

    emptyLabel.text(inPlay.length === 0 ? "No data" : "");

    if (inPlay.length >= 4) {
      const bw = Math.max(20, innerW / 11);
      const density = d3.contourDensity()
        .x(d => xS(d.bounce_x))
        .y(d => yS(d.bounce_y))
        .size([innerW, innerH])
        .bandwidth(bw)
        .thresholds(9)
        (inPlay);

      colorScale.domain([0, d3.max(density, d => d.value) || 1]);

      contourLayer.selectAll("path")
        .data(density, (_, i) => i)
        .join(
          enter => enter.append("path").attr("opacity", 0),
          update => update,
          exit => exit.transition().duration(200).attr("opacity", 0).remove()
        )
        .transition().duration(280)
        .attr("d", d3.geoPath())
        .attr("fill", d => colorScale(d.value))
        .attr("opacity", 0.85);
    } else {
      contourLayer.selectAll("path")
        .transition().duration(200).attr("opacity", 0).remove();
    }

    dotLayer.selectAll("circle")
      .data(inPlay, (_, i) => i)
      .join("circle")
      .attr("cx", d => xS(d.bounce_x))
      .attr("cy", d => yS(d.bounce_y))
      .attr("r", 2)
      .attr("fill", "white")
      .attr("opacity", 0.15);
  }

  return { update };
}


const DIR_COLORS = { T: "#2358a0", Wide: "#3d8a55", Body: "#b85a5a", Other: "#999" };

function renderDirBars(containerId, data, winData) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = "";

  if (!data) {
    el.innerHTML = `<span style="font-size:11px;color:#9aa">—</span>`;
    return;
  }

  const dirs = ["T", "Wide", "Body"];
  const total = dirs.reduce((s, d) => s + (data[d]?.n ?? 0), 0);
  if (total === 0) {
    el.innerHTML = `<span style="font-size:11px;color:#9aa">No in-play serves</span>`;
    return;
  }

  const track = document.createElement("div");
  track.className = "dir-track";
  const segs = document.createElement("div");
  segs.className = "dir-segments";

  dirs.forEach(dir => {
    const pct = data[dir]?.pct ?? 0;
    const seg = document.createElement("div");
    seg.className = "dir-seg";
    seg.style.width = `${pct}%`;
    seg.style.background = DIR_COLORS[dir];
    segs.appendChild(seg);
  });
  track.appendChild(segs);
  el.appendChild(track);

  const labels = document.createElement("div");
  labels.className = "dir-legend";
  dirs.forEach(dir => {
    const pct = data[dir]?.pct ?? 0;
    if (pct === 0) return;
    const win = winData?.[dir]?.win_pct;
    const item = document.createElement("div");
    item.className = "dir-legend-item";
    item.innerHTML = `
      <div class="dir-legend-dot" style="background:${DIR_COLORS[dir]}"></div>
      <span>${dir} <strong>${Math.round(pct)}%</strong>${win != null ? ` · <span class="win-rate">${Math.round(win)}% won</span>` : ""}</span>
    `;
    labels.appendChild(item);
  });
  el.appendChild(labels);
}


function computeDelta(breakdown, serveKey) {
  const normal = breakdown?.[`${serveKey}_normal`];
  const bp = breakdown?.[`${serveKey}_break_point`];
  if (!normal || !bp) return null;

  let biggest = null, maxAbs = 0;
  for (const dir of ["T", "Wide", "Body"]) {
    const delta = (bp[dir]?.pct ?? 0) - (normal[dir]?.pct ?? 0);
    if (Math.abs(delta) > maxAbs) { maxAbs = Math.abs(delta); biggest = { dir, delta }; }
  }
  return biggest;
}


const normalPanel = makeCourt("court-normal", "#2358a0");
const bpPanel = makeCourt("court-bp", "#e8a800");

let DATA = null;
let activeSide = "both";

function update(side) {
  if (!DATA) return;

  const { points, direction_breakdown } = DATA;
  const filtered = side === "both" ? points : points.filter(d => d.bounce_zone === side);
  const normal = filtered.filter(d => !d.is_break_point);
  const bp = filtered.filter(d => d.is_break_point);

  normalPanel.update(normal);
  bpPanel.update(bp);

  const fmt = arr => `n = ${arr.filter(d => d.result === "in").length} in-play`;
  d3.select("#count-normal").text(fmt(normal));
  d3.select("#count-bp").text(fmt(bp));

  const wr = DATA.win_rates;
  renderDirBars("bars-normal", direction_breakdown?.["s1_normal"], wr?.["s1_normal"]);
  renderDirBars("bars-bp",     direction_breakdown?.["s1_break_point"], wr?.["s1_break_point"]);

  const delta = computeDelta(direction_breakdown, "s1");
  if (delta && Math.abs(delta.delta) >= 1) {
    const sign = delta.delta > 0 ? "+" : "";
    d3.select("#delta-value").text(`${sign}${Math.round(delta.delta)}% ${delta.dir}`);
  } else {
    d3.select("#delta-value").text("—");
  }

  const speeds = filtered.filter(d => d.speed_mph != null).map(d => d.speed_mph);
  const inPlay = filtered.filter(d => d.result === "in");

  d3.select("#stat-total").text(filtered.length);
  d3.select("#stat-pct-in").text(
    filtered.length ? `${Math.round(inPlay.length / filtered.length * 100)}%` : "—"
  );
  d3.select("#stat-bp-pct").text(
    filtered.length ? `${Math.round(bp.length / filtered.length * 100)}%` : "—"
  );
  d3.select("#stat-speed").text(speeds.length ? d3.mean(speeds).toFixed(0) : "—");
}


d3.select("#serve-toggle").selectAll(".pill").on("click", function () {
  d3.select("#serve-toggle").selectAll(".pill").classed("active", false);
  d3.select(this).classed("active", true);
  activeSide = this.dataset.side;
  update(activeSide);
});


d3.json("data.json").then(data => {
  DATA = data;
  update(activeSide);
}).catch(() => {
  normalPanel.update([]);
  bpPanel.update([]);
  d3.select("#count-normal").text("run export.py to generate data");
  d3.select("#count-bp").text("");
});
