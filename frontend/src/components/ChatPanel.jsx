import { useState, useRef, useEffect } from "react";

const SUGGESTIONS = [
    "Which products have the most billing documents?",
    "Trace the full flow of billing document 90504248",
    "Show sales orders delivered but not billed",
    "Top 10 customers by total order amount",
    "Which billing documents are cancelled?",
    "Total revenue by sales organization",
    "Which plants handle the most deliveries?",
    "Show orders with partial delivery",
];

// Flow step component
function FlowTrace({ flow }) {
    if (!flow?.length) return null;
    return (
        <div className="flow-trace">
            <div className="flow-title">📋 Order-to-Cash Flow</div>
            <div className="flow-steps">
                {flow.map((step, i) => (
                    <div key={i} className="flow-step-wrap">
                        <div className={`flow-step ${step.status}`}>
                            <span className="flow-icon">{step.icon}</span>
                            <div className="flow-step-info">
                                <span className="flow-step-type">{step.type}</span>
                                {step.ids?.length > 0 ? (
                                    <span className="flow-step-ids">{step.ids.slice(0, 2).join(", ")}{step.ids.length > 2 ? ` +${step.ids.length - 2}` : ""}</span>
                                ) : (
                                    <span className="flow-step-missing">Not found</span>
                                )}
                            </div>
                            <span className={`flow-badge ${step.status}`}>{step.status === "found" ? "✓" : "✗"}</span>
                        </div>
                        {i < flow.length - 1 && <div className="flow-arrow">↓</div>}
                    </div>
                ))}
            </div>
        </div>
    );
}

// Guardrail message component
function GuardrailMsg({ message }) {
    return (
        <div className="guardrail-msg">
            <span className="guardrail-icon">🛡️</span>
            <span>{message}</span>
        </div>
    );
}

export default function ChatPanel({ apiBase, onHighlight, selectedNode }) {
    const [messages, setMessages] = useState([
        {
            role: "assistant",
            type: "data",
            content: "Hi! I can help you analyze the **Order to Cash** process.\n\nI query the real database and return data-backed answers. Ask me about:\n• Orders, deliveries, billing, payments\n• Product and customer analysis  \n• Broken or incomplete flows\n• Full trace of any document",
        },
    ]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [showSql, setShowSql] = useState({});
    const [searchQuery, setSearchQuery] = useState("");
    const [searchResults, setSearchResults] = useState(null);
    const [showSearch, setShowSearch] = useState(false);
    const bottomRef = useRef(null);
    const inputRef = useRef(null);

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    useEffect(() => {
        if (selectedNode) {
            const firstVal = Object.values(selectedNode.data || {})[0] || "";
            setInput(`Tell me about ${selectedNode.type} ${firstVal}`);
            inputRef.current?.focus();
        }
    }, [selectedNode]);

    const buildHistory = () =>
        messages.slice(-6).map((m) => ({ role: m.role, content: m.content || "" }));

    const appendAssistantToken = (token) => {
        setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.streaming) updated[updated.length - 1] = { ...last, content: last.content + token };
            return updated;
        });
    };

    const finalizeAssistantMsg = (extra) => {
        setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.streaming) updated[updated.length - 1] = { ...last, streaming: false, ...extra };
            return updated;
        });
    };

    const sendMessage = async (text) => {
        const msg = (text || input).trim();
        if (!msg || loading) return;
        setInput("");
        setLoading(true);

        setMessages((prev) => [
            ...prev,
            { role: "user", content: msg },
            { role: "assistant", type: "data", content: "", streaming: true, sql: null, resultCount: 0 },
        ]);

        try {
            const res = await fetch(`${apiBase}/api/chat/stream`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: msg, history: buildHistory() }),
            });

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    const raw = line.slice(6);
                    if (raw === "[DONE]") continue;
                    try {
                        const parsed = JSON.parse(raw);

                        if (parsed.type === "guardrail") {
                            finalizeAssistantMsg({ type: "guardrail", content: parsed.token, streaming: false });

                        } else if (parsed.type === "trace") {
                            if (parsed.highlighted_ids?.length) onHighlight(parsed.highlighted_ids);
                            finalizeAssistantMsg({
                                type: "trace",
                                content: "Here is the full Order-to-Cash flow:",
                                flow: parsed.flow,
                                streaming: false,
                            });

                        } else if (parsed.type === "meta") {
                            if (parsed.highlighted_ids?.length) onHighlight(parsed.highlighted_ids);
                            setMessages((prev) => {
                                const updated = [...prev];
                                const last = updated[updated.length - 1];
                                if (last?.streaming) {
                                    updated[updated.length - 1] = { 
                                        ...last, 
                                        sql: parsed.sql, 
                                        resultCount: parsed.result_count 
                                    };
                                }
                                return updated;
                            });

                        } else if (parsed.type === "token") {
                            appendAssistantToken(parsed.token);
                        }
                    } catch { }
                }
            }

            // Ensure streaming is done
            setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.streaming) updated[updated.length - 1] = { ...last, streaming: false };
                return updated;
            });

        } catch {
            setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                    role: "assistant", type: "error",
                    content: "❌ Could not connect to backend. Is the server running?",
                    streaming: false,
                };
                return updated;
            });
        }
        setLoading(false);
    };

    const handleSearch = async () => {
        if (!searchQuery.trim()) return;
        const res = await fetch(`${apiBase}/api/search?q=${encodeURIComponent(searchQuery)}`);
        const data = await res.json();
        setSearchResults(data);
    };

    const renderText = (text) =>
        (text || "")
            .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
            .replace(/^• /gm, "• ")
            .replace(/\n/g, "<br/>");

    return (
        <div className="chat-panel">
            {/* Header */}
            <div className="chat-header">
                <div>
                    <div className="chat-title">Chat with Graph</div>
                    <div className="chat-subtitle">Order to Cash</div>
                </div>
                <div className="agent-row">
                    <div className="agent-icon">D</div>
                    <div>
                        <div className="agent-name">Graph Agent</div>
                        <div className="agent-sub">Groq · llama3-70b</div>
                    </div>
                </div>
                <button className="search-toggle-btn" onClick={() => setShowSearch((s) => !s)} title="Search entities">
                    🔍︎
                </button>
            </div>

            {/* Semantic Search */}
            {showSearch && (
                <div className="search-bar">
                    <div className="search-row-input">
                        <input
                            className="search-input"
                            placeholder="Search customers, products, orders..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                        />
                        <button className="search-btn" onClick={handleSearch}>Go</button>
                    </div>
                    {searchResults && (
                        <div className="search-results">
                            {Object.entries(searchResults).map(([cat, rows]) =>
                                rows.length > 0 ? (
                                    <div key={cat} className="search-cat">
                                        <div className="search-cat-label">{cat} ({rows.length})</div>
                                        {rows.map((r, i) => (
                                            <div key={i} className="search-item"
                                                onClick={() => { sendMessage(`Tell me about ${Object.values(r)[0]}`); setShowSearch(false); }}>
                                                {Object.values(r).filter(Boolean).join(" · ").substring(0, 55)}
                                            </div>
                                        ))}
                                    </div>
                                ) : null
                            )}
                            {Object.values(searchResults).every(r => r.length === 0) && (
                                <div className="search-empty">No results found</div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* Messages */}
            <div className="chat-messages">
                {messages.map((msg, idx) => (
                    <div key={idx} className={`msg msg-${msg.role}`}>
                        {msg.role === "assistant" && <div className="avatar">D</div>}
                        <div className={`bubble ${msg.type === "guardrail" ? "bubble-guardrail" : ""}`}>

                            {/* Guardrail */}
                            {msg.type === "guardrail" ? (
                                <GuardrailMsg message={msg.content} />
                            ) : msg.streaming && !msg.content ? (
                                <div className="typing"><span /><span /><span /></div>
                            ) : msg.content ? (
                                <div className="msg-text" dangerouslySetInnerHTML={{ __html: renderText(msg.content) }} />
                            ) : null}

                            {/* Trace flow diagram */}
                            {msg.type === "trace" && msg.flow && <FlowTrace flow={msg.flow} />}

                            {/* SQL toggle */}
                            {msg.sql && (
                                <div className="sql-section">
                                    <button className="sql-toggle" onClick={() => setShowSql((p) => ({ ...p, [idx]: !p[idx] }))}>
                                        {showSql[idx] ? "▲ Hide SQL" : "▼ View SQL query"}
                                    </button>
                                    {showSql[idx] && <pre className="sql-code">{msg.sql}</pre>}
                                    {msg.resultCount !== undefined && (
                                        <span className="row-count">{msg.resultCount} row{msg.resultCount !== 1 ? "s" : ""} from database</span>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                ))}
                <div ref={bottomRef} />
            </div>

            {/* Suggestions */}
            {messages.length === 1 && (
                <div className="suggestions">
                    {SUGGESTIONS.map((s, i) => (
                        <button key={i} className="chip" onClick={() => sendMessage(s)}>{s}</button>
                    ))}
                </div>
            )}

            {/* Input */}
            <div className="chat-footer">
                <div className={`status-dot ${loading ? "pulse" : "active"}`} />
                <input
                    ref={inputRef}
                    className="chat-input"
                    placeholder="Ask about orders, billing, deliveries..."
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
                    disabled={loading}
                />
                <button className="send-btn" onClick={() => sendMessage()} disabled={loading || !input.trim()}>
                    {loading ? "···" : "Send"}
                </button>
            </div>
        </div>
    );
}