"""Simple static file server for the frontend."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

app = FastAPI()

# Serve static files from front/ directory
front_dir = Path(__file__).parent / "front"
app.mount("/", StaticFiles(directory=front_dir, html=True), name="static")
