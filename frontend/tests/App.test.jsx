import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";

const successResponse = {
  session_id: "s-test",
  reply: "The capital of France is Paris.",
  metadata: {
    resolution_source: "LIVE_INFERENCE",
    model: "gemini/gemini-3.5-flash-lite",
    latency_ms: 812,
    input_tokens: 42,
    output_tokens: 9,
    key_id: "key_1",
    fallback_attempts: 0,
  },
};

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Lyftr AI chat", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("sends a message and shows every required response metadata field", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(successResponse));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await user.type(screen.getByTestId("chat-input"), "What is the capital of France?");
    await user.click(screen.getByTestId("send-button"));

    expect(screen.getByTestId("chat-input")).toHaveValue("");
    const reply = await screen.findByTestId("assistant-message");
    expect(reply).toHaveTextContent("The capital of France is Paris.");
    expect(screen.getByTestId("meta-source")).toHaveTextContent(/^LIVE_INFERENCE$/);
    expect(screen.getByTestId("meta-model")).toHaveTextContent("gemini/gemini-3.5-flash-lite");
    expect(screen.getByTestId("meta-latency")).toHaveTextContent("812 ms");
    expect(screen.getByTestId("meta-input-tokens")).toHaveTextContent(/^42$/);
    expect(screen.getByTestId("meta-output-tokens")).toHaveTextContent(/^9$/);

    const request = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(request.message).toBe("What is the capital of France?");
    expect(request.session_id).toMatch(/^s-/);
    expect(request).not.toHaveProperty("history");
  });

  it("shows readable 503 errors instead of a blank screen", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "all providers unavailable" }, 503)));
    render(<App />);

    await user.type(screen.getByTestId("chat-input"), "Hello");
    await user.click(screen.getByTestId("send-button"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t send your message");
    expect(screen.getByRole("alert")).toHaveTextContent("all providers unavailable");
    expect(screen.queryByTestId("assistant-message")).not.toBeInTheDocument();
    expect(screen.getByTestId("chat-input")).toHaveValue("");
  });

  it("sends only the new message on follow-ups and includes the session prompt", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(successResponse))
      .mockResolvedValueOnce(jsonResponse({ ...successResponse, reply: "Paris has about 2 million people." }));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await user.type(screen.getByTestId("system-prompt-input"), "Answer concisely.");
    await user.type(screen.getByTestId("chat-input"), "Capital of France?");
    await user.click(screen.getByTestId("send-button"));
    await screen.findByTestId("assistant-message");
    await user.type(screen.getByTestId("chat-input"), "And its population?");
    await user.click(screen.getByTestId("send-button"));
    await waitFor(() => expect(screen.getAllByTestId("assistant-message")).toHaveLength(2));

    const first = JSON.parse(fetchMock.mock.calls[0][1].body);
    const second = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(first.system_prompt).toBe("Answer concisely.");
    expect(second).toEqual({
      session_id: first.session_id,
      message: "And its population?",
      system_prompt: "Answer concisely.",
    });
  });

  it("lists a successful chat after reload and reopens its SQLite history", async () => {
    const user = userEvent.setup();
    const firstSession = JSON.parse(JSON.stringify(successResponse));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(firstSession))
      .mockResolvedValueOnce(jsonResponse({
        session_id: "s-test",
        messages: [
          { role: "user", content: "What is the capital of France?" },
          { role: "assistant", content: "The capital of France is Paris.", metadata: firstSession.metadata },
        ],
      }));
    vi.stubGlobal("fetch", fetchMock);

    const first = render(<App />);
    await user.type(screen.getByTestId("system-prompt-input"), "Answer concisely.");
    await user.type(screen.getByTestId("chat-input"), "What is the capital of France?");
    await user.click(screen.getByTestId("send-button"));
    await screen.findByTestId("assistant-message");
    const sessionId = JSON.parse(fetchMock.mock.calls[0][1].body).session_id;
    expect(screen.getByTestId("history-item")).toHaveTextContent("What is the capital of France?");
    first.unmount();

    render(<App />);
    expect(screen.queryByTestId("assistant-message")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("history-item"));

    expect(await screen.findByTestId("assistant-message")).toHaveTextContent("The capital of France is Paris.");
    expect(screen.getByText("What is the capital of France?", { selector: ".user-message p" })).toBeInTheDocument();
    expect(screen.getByTestId("system-prompt-input")).toHaveValue("Answer concisely.");
    expect(fetchMock.mock.calls[1][0]).toContain(`/sessions/${sessionId}/messages`);
    expect(fetchMock.mock.calls[1][1].method).toBeUndefined();
  });

  it("opens an older chat by session ID and reports missing history", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ session_id: "s-old", messages: [] }))
      .mockResolvedValueOnce(jsonResponse({ detail: "session not found" }, 404));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await user.type(screen.getByTestId("history-session-input"), "s-old");
    await user.click(screen.getByTestId("history-open-button"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toContain("/sessions/s-old/messages");

    await user.type(screen.getByTestId("history-session-input"), "s-missing");
    await user.click(screen.getByTestId("history-open-button"));
    expect(await screen.findByRole("alert")).toHaveTextContent("session not found");
  });

  it("creates another fresh session without clearing the previous-chat list", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(successResponse)));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await user.type(screen.getByTestId("chat-input"), "First chat");
    await user.click(screen.getByTestId("send-button"));
    await screen.findByTestId("assistant-message");
    const firstId = JSON.parse(fetchMock.mock.calls[0][1].body).session_id;

    await user.click(screen.getByTestId("new-chat-button"));
    expect(screen.queryByTestId("assistant-message")).not.toBeInTheDocument();
    expect(screen.getByTestId("history-item")).toHaveTextContent("First chat");
    await user.type(screen.getByTestId("chat-input"), "Second chat");
    await user.click(screen.getByTestId("send-button"));
    await screen.findByTestId("assistant-message");

    const secondId = JSON.parse(fetchMock.mock.calls[1][1].body).session_id;
    expect(secondId).not.toBe(firstId);
    expect(screen.getAllByTestId("history-item")).toHaveLength(2);
  });

  it("starts a fresh session after a page reload simulation", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(successResponse)));
    vi.stubGlobal("fetch", fetchMock);

    const first = render(<App />);
    await user.type(screen.getByTestId("chat-input"), "First session");
    await user.click(screen.getByTestId("send-button"));
    await screen.findByTestId("assistant-message");
    first.unmount();

    render(<App />);
    expect(screen.queryByTestId("assistant-message")).not.toBeInTheDocument();
    await user.type(screen.getByTestId("chat-input"), "New session");
    await user.click(screen.getByTestId("send-button"));
    await screen.findByTestId("assistant-message");

    const firstId = JSON.parse(fetchMock.mock.calls[0][1].body).session_id;
    const secondId = JSON.parse(fetchMock.mock.calls[1][1].body).session_id;
    expect(secondId).not.toBe(firstId);
  });

  it("uses Enter to send but preserves Shift+Enter line breaks", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(successResponse));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    const input = screen.getByTestId("chat-input");

    await user.type(input, "Line one{Shift>}{Enter}{/Shift}Line two");
    expect(input).toHaveValue("Line one\nLine two");
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).message).toBe("Line one\nLine two");
  });
});
