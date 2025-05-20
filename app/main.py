from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI

import os
import redis.asyncio as redis


# 환경변수 로드
load_dotenv()

# Redis 클라이언트 전역 변수 선언
redis_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis_client = redis.Redis(
        host=os.getenv('REDIS_HOST'),
        port=os.getenv('REDIS_PORT'),
        db=os.getenv('REDIS_DB'),
        decode_responses=True,
    )
    yield
    await app.state.redis_client.aclose()

# FastAPI 애플리케이션 초기화
app = FastAPI(
    title="Asynchronous LLM API",
    description="비동기 LLM 처리를 위한 API 서버",
    version="1.0.0",
    swagger_ui_parameters={
        "syntaxHighlight": {
            "theme": "obsidian"
        }
    },
    lifespan=lifespan,
)

# 라우터 등록
from routers.router import router
app.include_router(router, prefix="/api", tags=["LLM Background"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="localhost", port=8000)