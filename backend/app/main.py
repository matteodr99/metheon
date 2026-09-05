from fastapi import FastAPI

app = FastAPI(title="Metheon API")


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "metheon"
    }