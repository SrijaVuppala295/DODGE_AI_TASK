import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";

const NODE_COLORS = {
    "Business Partner": "#E8A838",
    "Sales Order": "#4A90D9",
    "Sales Order Item": "#85C1E9",
    "Product": "#1ABC9C",
    "Outbound Delivery": "#5CB85C",
    "Delivery Item": "#A9DFBF",
    "Billing Document": "#9B59B6",
    "Billing Document Item": "#C39BD3",
    "Journal Entry": "#E74C3C",
    "Journal Item": "#F1948A",
    "Plant": "#7F8C8D",
    "Address": "#F39C12",
};

const NODE_RADIUS = {
    "Business Partner": 7, "Sales Order": 7, "Sales Order Item": 7,
    "Product": 7, "Outbound Delivery": 7, "Delivery Item": 7,
    "Billing Document": 7, "Billing Document Item": 7,
    "Journal Entry": 7, "Journal Item": 7,
    "Plant": 7, "Address": 7,
};

const SHOW_LABELS = ["Business Partner", "Sales Order", "Outbound Delivery", "Billing Document", "Product", "Journal Entry", "Plant"];

export default function GraphView({ nodes, edges, onSelectNode, highlightedIds, onExpandNode }) {
    const svgRef = useRef(null);
    const [popup, setPopup] = useState(null);
    const [popupPos, setPopupPos] = useState({ x: 0, y: 0 });

    useEffect(() => {
        if (!nodes.length || !svgRef.current) return;
        const container = svgRef.current.parentElement;
        const W = container.clientWidth || 900;
        const H = container.clientHeight || 700;

        const svg = d3.select(svgRef.current).attr("width", W).attr("height", H);
        svg.selectAll("*").remove();

        // Zoom container
        const g = svg.append("g");
        svg.call(
            d3.zoom().scaleExtent([0.05, 8])
                .on("zoom", (e) => g.attr("transform", e.transform))
        );

        // Arrow marker
        const defs = svg.append("defs");
        defs.append("marker")
            .attr("id", "arrowhead").attr("viewBox", "0 -4 8 8")
            .attr("refX", 18).attr("refY", 0)
            .attr("markerWidth", 5).attr("markerHeight", 5)
            .attr("orient", "auto")
            .append("path").attr("d", "M0,-4L8,0L0,4").attr("fill", "#B8D4F0").attr("opacity", 0.7);

        const nodeById = Object.fromEntries(nodes.map((n) => [n.id, n]));
        const simNodes = nodes.map((n) => ({ ...n }));
        const simEdges = edges
            .filter((e) => nodeById[e.source] && nodeById[e.target])
            .map((e) => ({ ...e }));

        const sim = d3.forceSimulation(simNodes)
            .force("link", d3.forceLink(simEdges).id((d) => d.id).distance(110).strength(0.45))
            .force("charge", d3.forceManyBody().strength(-220))
            .force("center", d3.forceCenter(W / 2, H / 2))
            .force("collision", d3.forceCollide((d) => (NODE_RADIUS[d.type] || 8) + 6));

        // Edges
        const link = g.append("g").selectAll("line").data(simEdges).join("line")
            .attr("stroke", "#B8D4F0")
            .attr("stroke-width", 1.3)
            .attr("stroke-opacity", 0.65)
            .attr("marker-end", "url(#arrowhead)");

        // Edge labels
        const linkLabel = g.append("g").selectAll("text").data(simEdges).join("text")
            .text((d) => d.label)
            .attr("font-size", 7)
            .attr("fill", "#aaa")
            .attr("text-anchor", "middle")
            .style("pointer-events", "none");

        // Node groups
        const node = g.append("g").selectAll("g").data(simNodes).join("g")
            .style("cursor", "pointer")
            .call(
                d3.drag()
                    .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
                    .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
                    .on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
            )
            .on("click", (e, d) => {
                e.stopPropagation();
                setPopup(d);
                setPopupPos({ x: e.clientX, y: e.clientY });
                onSelectNode(d);
            })
            .on("dblclick", (e, d) => {
                e.stopPropagation();
                onExpandNode(d.id);
            });

        // Circle
        node.append("circle")
            .attr("r", (d) => NODE_RADIUS[d.type] || 8)
            .attr("fill", (d) => NODE_COLORS[d.type] || "#aaa")
            .attr("fill-opacity", 0.88)
            .attr("stroke", "#fff")
            .attr("stroke-width", 1.5);

        // Labels for major nodes
        node.filter((d) => SHOW_LABELS.includes(d.type))
            .append("text")
            .text((d) => d.label.substring(0, 14))
            .attr("dy", (d) => -(NODE_RADIUS[d.type] || 8) - 4)
            .attr("text-anchor", "middle")
            .attr("font-size", 8)
            .attr("fill", "#444")
            .attr("font-weight", "500")
            .style("pointer-events", "none");

        node.append("title").text((d) =>
            `${d.type}: ${d.label}\nConnections: ${d.connections || 0}\nClick: inspect · Double-click: expand`
        );

        svg.on("click", () => { setPopup(null); onSelectNode(null); });

        sim.on("tick", () => {
            link
                .attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y)
                .attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
            linkLabel
                .attr("x", (d) => (d.source.x + d.target.x) / 2)
                .attr("y", (d) => (d.source.y + d.target.y) / 2);
            node.attr("transform", (d) => `translate(${d.x},${d.y})`);
        });

        return () => sim.stop();
    }, [nodes, edges]);

    // Highlight effect
    useEffect(() => {
        if (!svgRef.current) return;
        d3.select(svgRef.current).selectAll("circle")
            .transition().duration(250)
            .attr("stroke", (d) => highlightedIds.includes(d?.id) ? "#FFD700" : "#fff")
            .attr("stroke-width", (d) => highlightedIds.includes(d?.id) ? 4 : 1.5)
            .attr("fill-opacity", (d) =>
                !highlightedIds.length || highlightedIds.includes(d?.id) ? 0.88 : 0.15
            );
    }, [highlightedIds]);

    return (
        <div style={{ width: "100%", height: "100%", position: "relative" }}>
            <svg ref={svgRef} style={{ width: "100%", height: "100%" }} />

            {/* Hint bar */}
            <div className="graph-hint">
                Click to inspect &nbsp;·&nbsp; Double-click to expand &nbsp;·&nbsp; Scroll to zoom &nbsp;·&nbsp; Drag to pan
            </div>

            {/* Legend */}
            <div className="graph-legend">
                {Object.entries(NODE_COLORS).slice(0, 9).map(([type, color]) => (
                    <div key={type} className="legend-item">
                        <span className="legend-dot" style={{ background: color }} />
                        <span>{type}</span>
                    </div>
                ))}
            </div>

            {/* Node Popup */}
            {popup && (
                <div className="node-popup" style={{
                    left: Math.min(popupPos.x + 14, window.innerWidth - 335),
                    top: Math.min(popupPos.y - 20, window.innerHeight - 460),
                }}>
                    <div className="popup-header" style={{ borderLeft: `4px solid ${NODE_COLORS[popup.type] || "#ccc"}` }}>
                        <div>
                            <span className="popup-type">{popup.type}</span>
                            <span className="popup-label">{popup.label}</span>
                        </div>
                        <button className="popup-close" onClick={() => setPopup(null)}>✕</button>
                    </div>
                    <div className="popup-body">
                        {Object.entries(popup.data || {}).map(([k, v]) =>
                            v && String(v) !== "" && String(v) !== "null" ? (
                                <div key={k} className="popup-row">
                                    <span className="popup-key">{k}</span>
                                    <span className="popup-val">{String(v).substring(0, 55)}</span>
                                </div>
                            ) : null
                        )}
                    </div>
                    <div className="popup-footer">
                        <span className="popup-connections">🔗 {popup.connections || 0} connections</span>
                        <button className="expand-btn" onClick={() => { onExpandNode(popup.id); setPopup(null); }}>
                            ⊕ Expand
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}