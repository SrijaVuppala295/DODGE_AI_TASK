import { useState, useEffect } from "react";

const VIEWS = [
    { key: "delivered_not_billed", label: "Delivered, Not Billed", color: "#E8A838", icon: "📦", desc: "Orders fully delivered but invoice not yet raised — revenue recognition risk." },
    { key: "billed_no_delivery", label: "Billed, No Delivery", color: "#9B59B6", icon: "🧾", desc: "Billing documents raised without any recorded delivery — possible data issue." },
    { key: "partial_delivery", label: "Partial Delivery", color: "#4A90D9", icon: "⚠️", desc: "Orders only partially delivered — flow not complete." },
    { key: "cancelled_billings", label: "Cancelled Billings", color: "#E74C3C", icon: "❌", desc: "Billing documents that were cancelled — may indicate disputes or errors." },
];

export default function BrokenFlowsPanel({ apiBase }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [active, setActive] = useState("delivered_not_billed");

    useEffect(() => {
        fetch(`${apiBase}/api/analysis/broken-flows`)
            .then((r) => r.json())
            .then((d) => { setData(d); setLoading(false); })
            .catch(() => setLoading(false));
    }, []);

    if (loading) return <div className="loading"><div className="spinner" /><p>Analyzing flows...</p></div>;
    if (!data) return <div className="error-state">Could not load broken flows.</div>;

    const rows = data[active] || [];
    const activeView = VIEWS.find((v) => v.key === active);
    const getCount = (key) => data.summary?.[`${key}_count`] ?? data[key]?.length ?? 0;

    return (
        <div className="broken-flows">
            <div className="bf-header">
                <h2>Broken &amp; Incomplete Flows</h2>
                <p>Sales orders and billing documents with missing steps in the Order-to-Cash process.</p>
            </div>

            {/* Cards */}
            <div className="bf-cards">
                {VIEWS.map((v) => (
                    <button key={v.key} className={`bf-card ${active === v.key ? "active" : ""}`}
                        onClick={() => setActive(v.key)}
                        style={{ borderColor: active === v.key ? v.color : "transparent" }}>
                        <span className="bf-card-icon">{v.icon}</span>
                        <span className="bf-card-count" style={{ color: v.color }}>{getCount(v.key)}</span>
                        <span className="bf-card-label">{v.label}</span>
                    </button>
                ))}
            </div>

            {/* Description */}
            <div className="bf-desc" style={{ borderLeftColor: activeView?.color }}>
                {activeView?.desc}
            </div>

            {/* Table */}
            <div className="bf-table-wrap">
                {rows.length === 0 ? (
                    <div className="bf-empty">✅ No issues found in this category.</div>
                ) : (
                    <table className="bf-table">
                        <thead>
                            <tr>{Object.keys(rows[0]).map((k) => <th key={k}>{k}</th>)}</tr>
                        </thead>
                        <tbody>
                            {rows.map((row, i) => (
                                <tr key={i}>
                                    {Object.values(row).map((v, j) => (
                                        <td key={j}>{String(v ?? "—").substring(0, 40)}</td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
}