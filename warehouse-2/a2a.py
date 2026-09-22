import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import os
from agent import agent 
from server import mcp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("A2A_MAIN")

app = FastAPI(title="Warehouse 2 (H2) Agent API")

class AgentQuery(BaseModel):
    prompt: str
    thread_id: str = "H2 default_session"

@app.post("/chat")
async def chat_endpoint(query: AgentQuery):
    """
    Main A2A endpoint that passes user requests to the agent orchestrator and returns text response.
    """
    try:
        config = {"configurable": {"thread_id": query.thread_id}}
        result = await agent.ainvoke({"messages": [("user", query.prompt)]}, config)
        message = result["messages"][-1].content
        
        if isinstance(message, list):
            respond = "\n".join([b["text"] for b in message if isinstance(b, dict) and "text" in b])
        else:
            respond = str(message)

        return {"status": "success", "response": respond}
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


mcp_app = mcp.http_app(transport="sse", path="/sse")
app.mount("/mcp", mcp_app)


if __name__ == "__main__":
    uvicorn.run("a2a:app", host="127.0.0.1", port=8005, reload=True)