from fastapi import FastAPI

app = FastAPI(title="smart-hub-agent", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "smart-hub-agent"}
