#!/usr/bin/env python3
"""
Main entry point for deployment - imports and runs the FastAPI app from backend/main.py
This ensures the deployment system can find the app at the root level
"""

from backend.main import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
