import asyncio
import asyncpg
import aiohttp
import json
import logging
import signal
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from config import settings

logging.basicConfig(level=getattr(logging, settings.log_level), format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class Monitor:
    def __init__(self):
        self.conn: asyncpg.Connection | None = None
        self.session: aiohttp.ClientSession | None = None
        self.running = False

    async def connect_db(self):
        self.conn = await asyncpg.connect(
            host=settings.db_host,
            port=settings.db_port,
            user=settings.db_user,
            password=settings.db_pass,
            database=settings.db_name
        )
        await self.conn.execute(f"LISTEN {settings.channel};")
        logger.info(f"Listening on channel {settings.channel}")

    async def connect_http(self):
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(timeout=timeout)

    async def trigger_validation(self, payload: str):
        try:
            data = json.loads(payload)
            email_id = data["id"]
            url = f"{settings.api_gateway_url}/validate/{email_id}"
            async with self.session.post(url, json={"email": data["email"]}) as resp:
                if resp.status == 200:
                    logger.info(f"Validation triggered for email_id {email_id}")
                else:
                    logger.warning(f"Validation failed for {email_id}: {resp.status}")
        except Exception as e:
            logger.error(f"Error triggering validation: {e}")

    async def listen_loop(self):
        while self.running:
            try:
                notification = await self.conn.wait_for_notification(1.0)  # 1s timeout
                if notification:
                    logger.debug(f"Received: {notification.channel} - {notification.payload}")
                    await self.trigger_validation(notification.payload)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Listen error: {e}")
                await asyncio.sleep(5)

    async def start(self):
        await self.connect_db()
        await self.connect_http()
        self.running = True
        logger.info("Monitor started")
        await self.listen_loop()

    async def stop(self):
        self.running = False
        if self.session:
            await self.session.close()
        if self.conn:
            await self.conn.close()
        logger.info("Monitor stopped")

monitor = Monitor()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await monitor.start()
    yield
    await monitor.stop()

app = FastAPI(title="Table Monitor Microservice", lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "healthy", "listening": monitor.running}

@app.get("/")
async def root():
    return {"message": "Table Monitor is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)