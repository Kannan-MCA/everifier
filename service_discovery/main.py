import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel, Field, HttpUrl
from typing import Dict, List
import uvicorn

app = FastAPI(title="Service Discovery")

HEARTBEAT_TTL = timedelta(seconds=90)  # Expire services not heartbeating in 90 seconds

class ServiceInfo(BaseModel):
    name: str = Field(..., description="Unique service name")
    address: str = Field(..., description="Service HTTP URL or IP address with port")
    last_heartbeat: datetime = Field(default_factory=datetime.utcnow)

# In-memory registry: service name -> list of ServiceInfo
registry: Dict[str, List[ServiceInfo]] = {}

@app.post("/register")
async def register_service(info: ServiceInfo):
    now = datetime.utcnow()
    info.last_heartbeat = now
    services = registry.setdefault(info.name, [])
    # Replace if this address already registered
    existing = next((svc for svc in services if svc.address == info.address), None)
    if existing:
        existing.last_heartbeat = now
    else:
        services.append(info)
    return {"message": f"Service {info.name} registered at {info.address}"}

@app.post("/heartbeat")
async def heartbeat(name: str = Body(...), address: str = Body(...)):
    now = datetime.utcnow()
    services = registry.get(name)
    if not services:
        raise HTTPException(status_code=404, detail="Service name not registered")
    existing = next((svc for svc in services if svc.address == address), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Service address not registered")
    existing.last_heartbeat = now
    return {"message": "Heartbeat updated"}

@app.post("/deregister")
async def deregister_service(name: str = Body(...), address: str = Body(...)):
    services = registry.get(name)
    if not services:
        return {"message": "No such service registered, nothing to deregister"}
    registry[name] = [svc for svc in services if svc.address != address]
    if not registry[name]:
        del registry[name]
    return {"message": f"Service {name} at {address} deregistered"}

@app.get("/services/{name}", response_model=List[str])
async def get_service_addresses(name: str):
    services = registry.get(name)
    if not services:
        raise HTTPException(status_code=404, detail="No such service registered")
    # Filter out expired
    now = datetime.utcnow()
    valid_services = [svc.address for svc in services if now - svc.last_heartbeat <= HEARTBEAT_TTL]
    if not valid_services:
        raise HTTPException(status_code=404, detail="No healthy instances available")
    return valid_services

async def cleanup_loop():
    while True:
        now = datetime.utcnow()
        expired_names = []
        for name, services in list(registry.items()):
            registry[name] = [svc for svc in services if now - svc.last_heartbeat <= HEARTBEAT_TTL]
            if not registry[name]:
                expired_names.append(name)
        for name in expired_names:
            del registry[name]
        await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_loop())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8500)
