# agent_mcp_wiki.py
# uv run agent_mcp_wiki.py
import os, time
import logging, sys
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import ListSortOrder
from azure.ai.agents.models import (
    McpTool,
    SubmitToolApprovalAction,
    RequiredMcpToolCall,
    ToolApproval,
    ListSortOrder,
)

logger = logging.getLogger("azure")
logger.setLevel(logging.WARNING)          # DEBUG gives you request/response details
handler = logging.StreamHandler(stream=sys.stdout)
handler.setLevel(logging.WARNING)
logger.addHandler(handler)

# Load environment variables from .env file
load_dotenv()

def print_run_diagnostics(thread_id: str, run_id: str):
        run = project_client.agents.runs.get(thread_id=thread_id, run_id=run_id)
        print(f"\nRUN: status={run.status}")
        # Many builds expose last_error on failed runs:
        if getattr(run, "last_error", None):
            err = run.last_error
            print(f"RUN ERROR: code={getattr(err, 'code', '?')} msg={getattr(err, 'message', '')}")

        # List run steps (ordered) and show any step-level errors or tool call info
        steps = project_client.agents.run_steps.list(
            thread_id=thread_id,
            run_id=run_id,
            order=ListSortOrder.ASCENDING
        )
        print("\nRUN STEPS:")
        for s in steps:
            # RunStep is dict-like; these keys exist across builds:
            s_type = s.get("type")
            s_status = s.get("status")
            s_err = s.get("last_error") or s.get("error")
            print(f" - step {s.get('id')} type={s_type} status={s_status}")
            if s_err:
                print(f"   step_error: {getattr(s_err, 'code', None) or s_err.get('code')} - "
                  f"{getattr(s_err, 'message', None) or s_err.get('message')}")
            # Tool calls (if any)
            details = s.get("step_details") or {}
            tool_calls = details.get("tool_calls") or []
            for tc in tool_calls:
                print(f"   tool_call: type={tc.get('type')} name={tc.get('name')} "
                      f"server_label={tc.get('server_label')} status={tc.get('status')}")


project_client = AIProjectClient(
    endpoint=os.environ["PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(),
    logging_enable=True,
)

mcp_tool = McpTool(
    server_label=os.environ.get("MCP_SERVER_LABEL", "wiki"),
    server_url=os.environ.get("MCP_SERVER_URL"),
    allowed_tools=[],  # optional: restrict to specific tool names exposed by your MCP
)

# If you want to bypass approvals entirely for faster dev:
# mcp_tool.set_approval_mode("never")  # (supported per docs)

with project_client:
    agents = project_client.agents

    # 1) Create the agent with the MCP tool attached
    agent = agents.create_agent(
        model=os.environ["MODEL_DEPLOYMENT_NAME"],
        name="wiki-mcp-agent",
        instructions="Use the MCP 'answerQ' tool to answer trivia via Wikipedia.",
        tools=mcp_tool.definitions,  # <- important
    )
    print("Agent:", agent.id)

    # 2) Create a thread and add a user message
    thread = agents.threads.create()
    project_client.agents.messages.create(
        thread_id=thread.id, role="user", content="Paetongtarn Shinawatra"
    )
    print("thread.id:", thread.id)
    
    # 3) Prepare tool headers (e.g., Authorization) and run
    #if os.getenv("MCP_BEARER"):
    #    mcp_tool.update_headers("Authorization", f"Bearer {os.environ['MCP_BEARER']}")

    mcp_tool.update_headers("Accept", "application/json, text/event-stream")
    mcp_tool.update_headers("MCP-Protocol-Version", "2025-06-18")
    run = agents.runs.create(
        thread_id=thread.id,
        agent_id=agent.id,
        tool_resources=mcp_tool.resources,  # <- where headers are passed
    )

    print("Run ID:", run.id)
    # 4) Handle approval workflow if enabled (default is 'always')
    while run.status in ("queued", "in_progress", "requires_action"):
        time.sleep(1)
        run = agents.runs.get(thread_id=thread.id, run_id=run.id)

        if run.status == "requires_action" and isinstance(run.required_action, SubmitToolApprovalAction):
            approvals = []
            for tc in run.required_action.submit_tool_approval.tool_calls:
                if isinstance(tc, RequiredMcpToolCall):
                    approvals.append(
                        ToolApproval(tool_call_id=tc.id, approve=True, headers=mcp_tool.headers)
                    )
            if approvals:
                project_client.agents.runs.submit_tool_outputs(
                    thread_id=thread.id, run_id=run.id, tool_approvals=approvals
                )

    print("Run status:", run.status)
    if run.status == "FAILED":
        print_run_diagnostics(thread.id, run.id)

    # 5) Print resulting conversation
    msgs = list(project_client.agents.messages.list(thread_id=thread.id, order=ListSortOrder.ASCENDING))
    print("\n--- Conversation ---")
    for m in msgs:
        if m.text_messages:
            print(f"{m.role.upper()}: {m.text_messages[-1].text.value}")
            
    