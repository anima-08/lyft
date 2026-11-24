import { useEffect, useRef, useState } from "react";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");

const STARTER_PROMPTS = [
  { title: "Explain a concept", text: "Explain how API key failover works in simple terms.", icon: "spark" },
  { title: "Plan something", text: "Help me plan a focused two-hour study session.", icon: "list" },
  { title: "Write creatively", text: "Write a short welcome message for a resilient AI chat app.", icon: "pen" },
];

function createSessionId() {
  const randomPart = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `s-${randomPart}`;
}

function SparkIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" />
      <path d="m18.5 15 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

function PromptIcon({ type }) {
  if (type === "list") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01" />
      </svg>
    );
  }
  if (type === "pen") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="m15 5 4 4M4 20l4.5-1L20 7.5a2.1 2.1 0 0 0-3-3L5.5 16 4 20Z" />
      </svg>
    );
  }
  return <SparkIcon />;
}

function ResponseMetadata({ metadata }) {
  const cached = metadata.resolution_source === "LLM_CACHE";
  return (
    <div className="metadata" aria-label="Response metadata">
      <div className="metadata-primary">
        <span className={`source-badge ${cached ? "cached" : "live"}`} data-testid="meta-source">
          {metadata.resolution_source}
        </span>
        <span className="model-name" data-testid="meta-model">{metadata.model}</span>
      </div>
      <div className="metadata-stats">
        <span className="stat"><span data-testid="meta-latency">{metadata.latency_ms} ms</span><small>latency</small></span>
        <span className="stat"><span data-testid="meta-input-tokens">{metadata.input_tokens}</span><small>input tokens</small></span>
        <span className="stat"><span data-testid="meta-output-tokens">{metadata.output_tokens}</span><small>output tokens</small></span>
      </div>
    </div>
  );
}

function readableError(payload, status) {
  const detail = payload?.detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || "Invalid request").join("; ");
  }
  return detail || `The server returned HTTP ${status}. Please try again.`;
}

export default function App() {
  const [sessionId] = useState(createSessionId);
  const [messages, setMessages] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [pending, setPending] = useState(false);
  const [copied, setCopied] = useState(false);
  const conversationEnd = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (messages.length > 0 || pending) {
      conversationEnd.current?.scrollIntoView?.({ behavior: messages.length > 1 ? "smooth" : "auto", block: "end" });
    }
  }, [messages, pending]);

  async function sendMessage(overrideText) {
    const text = (overrideText ?? chatInput).trim();
    if (!text || pending) return;

    setChatInput("");
    setMessages((current) => [...current, { role: "user", content: text }]);
    setPending(true);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 65000);

    try {
      const body = { session_id: sessionId, message: text };
      const prompt = systemPrompt.trim();
      if (prompt) body.system_prompt = prompt;

      const response = await fetch(`${API_BASE_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(readableError(payload, response.status));
      if (!payload?.reply || !payload?.metadata) throw new Error("The server returned an invalid response. Please try again.");

      setMessages((current) => [
        ...current,
        { role: "assistant", content: payload.reply, metadata: payload.metadata },
      ]);
    } catch (error) {
      const message = error.name === "AbortError"
        ? "The request timed out. Please try again."
        : error.message || "Unable to reach the server. Please try again.";
      setMessages((current) => [...current, { role: "error", content: message }]);
    } finally {
      clearTimeout(timeout);
      setPending(false);
      inputRef.current?.focus();
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    void sendMessage();
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void sendMessage();
    }
  }

  async function copySessionId() {
    try {
      await navigator.clipboard.writeText(sessionId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="Lyftr AI home">
          <span className="brand-mark"><SparkIcon /></span>
          <span>Lyftr<span className="brand-ai">AI</span></span>
        </a>

        <div className="workspace-label">YOUR WORKSPACE</div>
        <div className="session-card">
          <div className="session-heading">
            <span className="session-icon">L</span>
            <div><strong>Current conversation</strong><span><i />New session</span></div>
          </div>
          <button className="session-id" type="button" onClick={copySessionId} title="Copy session ID">
            <span>{sessionId.slice(0, 18)}…</span><span>{copied ? "Copied" : "Copy ID"}</span>
          </button>
        </div>

        <div className="prompt-settings">
          <label htmlFor="system-prompt"><span>System prompt</span><small>OPTIONAL</small></label>
          <textarea
            id="system-prompt"
            data-testid="system-prompt-input"
            value={systemPrompt}
            onChange={(event) => setSystemPrompt(event.target.value)}
            maxLength={4000}
            rows={6}
            placeholder="Set the tone, role, or instructions for this session…"
          />
          <p>Applied to this session and remembered for follow-up messages.</p>
        </div>

        <div className="resilience-card">
          <div className="resilience-title"><span className="pulse-dot" />Built to keep going</div>
          <p>Automatic key fallback and smart response caching keep your conversation moving.</p>
          <div><span>Key failover</span><span>Response cache</span></div>
        </div>

        <div className="sidebar-footer"><span className="status-dot" />Powered by LiteLLM <span>·</span> SQLite</div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div><span className="mobile-brand"><SparkIcon /></span><h1>AI Chat</h1><span className="topbar-divider" /><p>Context-aware. Failure-ready.</p></div>
          <span className="online-pill"><i />Online</span>
        </header>

        <section className="conversation" aria-live="polite" aria-label="Conversation">
          {messages.length === 0 && (
            <div className="welcome">
              <div className="welcome-mark"><SparkIcon /></div>
              <span className="eyebrow">A SMARTER WAY TO CHAT</span>
              <h2>What can I help you with?</h2>
              <p>Ask a question, explore an idea, or pick up where you left off. <br />Your conversation stays right here.</p>
              <div className="starter-grid">
                {STARTER_PROMPTS.map((prompt) => (
                  <button key={prompt.title} type="button" onClick={() => void sendMessage(prompt.text)}>
                    <span className="prompt-icon"><PromptIcon type={prompt.icon} /></span>
                    <span><strong>{prompt.title}</strong><small>{prompt.text}</small></span>
                    <ArrowIcon />
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="message-list">
            {messages.map((message, index) => {
              if (message.role === "error") {
                return <div className="error-message" role="alert" key={`error-${index}`}><strong>Couldn’t send your message</strong><p>{message.content}</p></div>;
              }
              if (message.role === "user") {
                return (
                  <article className="user-message" key={`user-${index}`}>
                    <div className="message-label">YOU</div>
                    <p>{message.content}</p>
                  </article>
                );
              }
              return (
                <article className="assistant-message" data-testid="assistant-message" key={`assistant-${index}`}>
                  <div className="assistant-avatar"><SparkIcon /></div>
                  <div className="assistant-content">
                    <div className="message-label">LYFTR AI</div>
                    <p className="reply-text">{message.content}</p>
                    <ResponseMetadata metadata={message.metadata} />
                  </div>
                </article>
              );
            })}
            {pending && (
              <div className="pending-message" role="status">
                <div className="assistant-avatar"><SparkIcon /></div>
                <div><div className="message-label">LYFTR AI</div><div className="typing-indicator"><i /><i /><i /></div><span>Finding the best route…</span></div>
              </div>
            )}
            <div ref={conversationEnd} />
          </div>
        </section>

        <footer className="composer-area">
          <form className="composer" onSubmit={handleSubmit}>
            <textarea
              ref={inputRef}
              data-testid="chat-input"
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              maxLength={4000}
              placeholder="Message Lyftr AI…"
              aria-label="Message Lyftr AI"
            />
            <button data-testid="send-button" type="submit" disabled={!chatInput.trim() || pending} aria-label="Send message">
              <ArrowIcon />
            </button>
          </form>
          <div className="composer-hint"><span><kbd>Enter</kbd> to send <i>·</i> <kbd>Shift + Enter</kbd> for a new line</span><span>AI can make mistakes. Check important info.</span></div>
        </footer>
      </main>
    </div>
  );
}
