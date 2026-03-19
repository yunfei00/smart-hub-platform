from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent.core.config import load_rules
from agent.core.exceptions import AgentError
from agent.core.models import (
    CleanRequest,
    CleanResponse,
    RulesResponse,
    ScanRequest,
    ScanResponse,
)
from agent.core.scanner import clean_files, scan_path

app = FastAPI(title="smart-hub-agent", version="0.1.0")


@app.exception_handler(AgentError)
async def handle_agent_error(_: Request, exc: AgentError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


@app.exception_handler(Exception)
async def handle_unknown_error(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": f"internal error: {exc}"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "smart-hub-agent"}


@app.get("/rules", response_model=RulesResponse)
def get_rules() -> RulesResponse:
    rules = load_rules()
    return RulesResponse(rules=rules)


@app.post("/scan", response_model=ScanResponse)
def scan(payload: ScanRequest) -> ScanResponse:
    rules = load_rules()
    return scan_path(payload.path, rules)


@app.post("/clean", response_model=CleanResponse)
def clean(payload: CleanRequest) -> CleanResponse:
    rules = load_rules()
    return clean_files(payload.rule_id, payload.files, rules)
