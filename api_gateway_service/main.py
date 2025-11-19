from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
import httpx
import os
from jose import JWTError, jwt
from starlette.status import HTTP_401_UNAUTHORIZED
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Config
API_PORT = int(os.getenv("API_PORT", 8000))
API_HOST = os.getenv("API_HOST", "0.0.0.0")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key")
JWT_ALGORITHM = "HS256"

# Rate Limiting setup
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Email Validation API Gateway")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

origins = [
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Validate JWT token
async def verify_token(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
        return payload
    except JWTError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")

backend_services = {
    "syntax_mx": "http://syntax-mx-service:8001",
    "smtp": "http://smtp-service:8002",
    "catchall": "http://catchall-service:8003",
}

@app.get("/")
async def root():
    return {"message": "Welcome to the Email Validation API Gateway"}

@app.post("/validate/{service_name}")
@limiter.limit("10/minute")
async def proxy_validation(service_name: str, request: Request, token_payload: dict = Depends(verify_token)):
    if service_name not in backend_services:
        raise HTTPException(status_code=404, detail="Service not found")

    body = await request.json()

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{backend_services[service_name]}/validate", json=body)
            response.raise_for_status()
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail=f"Failed to connect to {service_name} service")
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)

    return response.json()
