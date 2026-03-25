import { useState, useEffect, useCallback } from "react";
import GraphView from "./components/GraphView";
import ChatPanel from "./components/ChatPanel";
import BrokenFlowsPanel from "./components/BrokenFlowsPanel";
import "./App.css";

export const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function App() {
    const [graphData, setGraphData] = useState({ nodes: [], edges: [] });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [selectedNode, setSelectedNode] = useState(null);
    const [highlightedIds, setHighlightedIds] = useState([]);
    const [activeTab, setActiveTab] = useState("graph");

    useEffect(() => {
        fetch(`${API_BASE}/api/graph`)
            .then((r) => { if (!r.ok) throw new Error("Backend unreachable"); return r.json(); })
            .then((data) => { setGraphData(data); setLoading(false); })
            .catch((e) => { setError(e.message); setLoading(false); });
    }, []);

    const handleHighlight = useCallback((ids) => setHighlightedIds(ids), []);
    const clearHighlight = useCallback(() => setHighlightedIds([]), []);

    const handleExpandNode = useCallback(async (nodeId) => {
        try {
            const res = await fetch(`${API_BASE}/api/node/${nodeId}/expand`);
            const data = await res.json();
            setGraphData((prev) => {
                const existingNodeIds = new Set(prev.nodes.map((n) => n.id));
                const existingEdgeIds = new Set(prev.edges.map((e) => e.id));
                return {
                    nodes: [...prev.nodes, ...data.nodes.filter((n) => !existingNodeIds.has(n.id))],
                    edges: [...prev.edges, ...data.edges.filter((e) => !existingEdgeIds.has(e.id))],
                };
            });
        } catch (e) {
            console.error("Expand failed:", e);
        }
    }, []);

    return (
        <div className="app">
            <header className="app-header">
                <div className="header-left">
                    <span className="breadcrumb">Mapping</span>
                    <span className="sep">/</span>
                    <span className="page-title">Order to Cash</span>
                </div>
                <div className="header-tabs">
                    <button className={`tab-btn ${activeTab === "graph" ? "active" : ""}`} onClick={() => setActiveTab("graph")}>
                        🕸 Graph View
                    </button>
                    <button className={`tab-btn ${activeTab === "broken" ? "active" : ""}`} onClick={() => setActiveTab("broken")}>
                        ⚠️ Broken Flows
                    </button>
                </div>
                <div className="header-stats">
                    {!loading && !error && (
                        <>
                            <span className="stat">{graphData.nodes.length} nodes</span>
                            <span className="stat">{graphData.edges.length} edges</span>
                            {highlightedIds.length > 0 && (
                                <button className="clear-hl" onClick={clearHighlight}>✕ Clear highlights</button>
                            )}
                        </>
                    )}
                </div>
            </header>

            <div className="app-body">
                <div className="main-area">
                    {activeTab === "graph" ? (
                        loading ? (
                            <div className="loading"><div className="spinner" /><p>Building graph...</p></div>
                        ) : error ? (
                            <div className="error-state">
                                <h3>⚠️ Cannot connect to backend</h3>
                                <p>Make sure FastAPI is running at <code>{API_BASE}</code></p>
                                <code>uvicorn main:app --reload</code>
                            </div>
                        ) : (
                            <GraphView
                                nodes={graphData.nodes}
                                edges={graphData.edges}
                                selectedNode={selectedNode}
                                onSelectNode={setSelectedNode}
                                highlightedIds={highlightedIds}
                                onExpandNode={handleExpandNode}
                            />
                        )
                    ) : (
                        <BrokenFlowsPanel apiBase={API_BASE} />
                    )}
                </div>

                <ChatPanel
                    apiBase={API_BASE}
                    onHighlight={handleHighlight}
                    selectedNode={selectedNode}
                />
            </div>
        </div>
    );
}