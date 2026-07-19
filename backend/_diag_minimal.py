import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from papis.database import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("LIFESPAN: about to call init_db")
    await asyncio.to_thread(init_db, dev_mode=False)
    print("LIFESPAN: init_db returned")
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8766)
