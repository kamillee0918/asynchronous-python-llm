from fastapi import FastAPI
from dotenv import load_dotenv

import os
import redis
import sys
import pathlib

# 현재 디렉토리의 부모 디렉토리를 Python 경로에 추가
sys.path.append(str(pathlib.Path(__file__).parent.parent.resolve()))

# 환경변수 로드
load_dotenv()

# FastAPI 애플리케이션 초기화
app = FastAPI(
    title="Asynchronous LLM API",
    description="비동기 LLM 처리를 위한 API 서버",
    version="1.0.0",
    swagger_ui_parameters={
        "syntaxHighlight": {
            "theme": "obsidian"
        }
    }
)

# Redis 연결 설정
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST'),
    port=os.getenv('REDIS_PORT'),
    db=os.getenv('REDIS_DB'),
    decode_responses=True,
)

# 라우터 등록
from routers.router import router
app.include_router(router, prefix="/api", tags=["LLM Background"])

# 애플리케이션 시작 시 실행될 이벤트
@app.on_event("startup")
async def startup_event():
    print("Application startup")

# 애플리케이션 종료 시 실행될 이벤트
@app.on_event("shutdown")
async def shutdown_event():
    print("Application shutdown")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="localhost", port=8000)