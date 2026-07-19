from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import health, import_, review, vocab
from app.services import dictionary

app = FastAPI(title="Cantonese Dialogue Tracker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(import_.router)
app.include_router(review.router)
app.include_router(vocab.router)


@app.on_event("startup")
def _load_dictionary() -> None:
    dictionary.load()
