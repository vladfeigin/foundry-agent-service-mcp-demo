# server.py
import contextlib, os, requests
from urllib.parse import quote
from collections.abc import AsyncIterator

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send
import uvicorn

# ---------- MCP application ----------
app = Server("wiki-mcp")

# Tool: answerQ(question) -> summary text from Wikipedia
@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "answerQ":
        raise ValueError(f"Unknown tool: {name}")
    question = (arguments or {}).get("question", "").strip()
    if not question:
        return [types.TextContent(type="text", text="Please provide a question/topic.")]
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(question)}"
        r = requests.get(url, timeout=6, headers={"User-Agent": "WikiMCP/0.1"})
        if r.ok and r.json().get("extract"):
            return [types.TextContent(type="text", text=r.json()["extract"])]
        return [types.TextContent(type="text", text=f"Sorry, I couldn’t find “{question}”.")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Lookup failed: {e}")]

# Tool schema so clients discover it via `tools/list`
@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="answerQ",
            description="Answer a trivia question using Wikipedia summary.",
            inputSchema={
                "type": "object",
                "required": ["question"],
                "properties": {
                    "question": {"type": "string", "description": "Question or topic to look up"}
                },
            },
        )
    ]

# ---------- Boilerplate: Streamable HTTP (stateless, JSON responses) ----------
session_manager = StreamableHTTPSessionManager(
    app=app,
    event_store=None,      # no persistence
    json_response=True,    # JSON responses (nice for curl/jq)
    stateless=True,        # stateless mode
)

async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
    await session_manager.handle_request(scope, receive, send)

@contextlib.asynccontextmanager
async def lifespan(_: Starlette) -> AsyncIterator[None]:
    async with session_manager.run():
        yield

async def healthz(request):
    return JSONResponse({"ok": True})

starlette_app = Starlette(
    routes=[
        Mount("/mcp", app=handle_streamable_http),   # endpoint: POST http://localhost:4200/mcp
        # simple health check for sanity:
        Route("/healthz", healthz),
    ],
    lifespan=lifespan,
)

if __name__ == "__main__":
    uvicorn.run(starlette_app, host="0.0.0.0", port=int(os.getenv("PORT", "4200")))