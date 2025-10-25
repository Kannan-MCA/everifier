from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.routes import router
from .database import init_db, test_connection 

app = FastAPI(
    title="Email Validator API",
    description="Production-grade email validation with SMTP verification",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database
@app.on_event("startup")
async def startup_event():
    # Use init_db() for development (drops and recreates)
    # Use create_tables_if_not_exists() for production (safe)
    init_db()  # Change to create_tables_if_not_exists() in production

# Include routers
app.include_router(router)

@app.get("/")
async def root():
    return {
        "message": "Email Validator API",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}