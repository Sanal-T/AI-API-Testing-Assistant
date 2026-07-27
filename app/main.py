from fastapi import FastAPI

app = FastAPI(
    title="AI API Testing Assistant",
    version="1.0.0"
)

@app.get("/")
def home():
    return {
        "message": "AI API Testing Assistant is running!"
    }