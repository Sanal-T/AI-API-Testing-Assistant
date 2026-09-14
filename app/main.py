from fastapi import FastAPI
from app.api.upload import router as upload_router
from app.api.test_runs import router as test_runs_router

app = FastAPI(
    title="AI API Testing Assistant",
    version="1.0.0"
)

app.include_router(upload_router)
app.include_router(test_runs_router)

@app.get("/")
def home():
    return {
        "message": "AI API Testing Assistant is running!"
    }
