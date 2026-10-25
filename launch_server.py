"""Starts the Central Relay Server."""

import uvicorn

if __name__ == "__main__":
    print("Starting PokeCompanion NetBridge Relay Server on http://127.0.0.1:8000...")
    uvicorn.run("src.server.server:app", host="127.0.0.1", port=8000, reload=False)

