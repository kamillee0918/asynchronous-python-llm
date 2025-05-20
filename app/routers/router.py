from dotenv import load_dotenv
from fastapi import APIRouter, Request
from typing import List
from pydantic import BaseModel
from openai import AsyncOpenAI

import uuid
import os
import asyncio
import redis.asyncio as redis


# 환경변수 호출
load_dotenv()

router = APIRouter()

# 고정값 지정
NUM_WORKERS = 4 # 쓰레드 풀 크기와 일치

# Redis 연결
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST'),
    port=os.getenv('REDIS_PORT'),
    db=os.getenv('REDIS_DB'),
    decode_responses=True,
)

# 비동기 방식의 큐 구현
task_queue = asyncio.Queue()

class PromptList(BaseModel):
    """PromptList 모델 클래스 정의"""
    prompts: List[str] # 프롬프트 리스트


async def background_worker():
    """백그라운드 워커 함수"""
    while True:
        try:
            task_id, prompt = await task_queue.get()
            # INFO: 직접 비동기 함수 호출로 변경
            await process_llm_task(task_id, prompt)
            task_queue.task_done()
        except Exception as e:
            print(f"Background worker error: {e}")
            continue


async def process_llm_task(task_id: str, prompt: str):
    """LLM 작업 처리 함수"""
    try:
        client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))

        # Redis 상태 업데이트
        await redis_client.hset(
            f"task:{task_id}",
            mapping={
                "status": "processing",
                "progress": "0"
            }
        )

        await redis_client.hset(
            f"task:{task_id}", "progress", "25"
        )

        # OpenAI가 지원하는 모델 호출
        response = await client.responses.create(
            model="gpt-3.5-turbo",
            input=prompt,
            max_output_tokens=100, # 최대 출력 토큰 수
            temperature=0.7
        )
        # print("# response:", response)

        await redis_client.hset(
            f"task:{task_id}", "progress", "75"
        )

        # Redis 완료 상태 업데이트
        await redis_client.hset(
            f"task:{task_id}",
            mapping={
                "status": "completed",
                "result": response.output_text,
                "progress": "100"
            }
        )

        # 24시간이 지나면 만료(키 삭제)
        await redis_client.expire(
            f"task:{task_id}",
            86400
        )
    
    except Exception as e:
        # Redis 오류 상태 업데이트
        await redis_client.hset(
            f"task:{task_id}",
            mapping={
                "status": "failed",
                "error": str(e)
            }
        )


@router.post("/tasks")
async def create_tasks(prompts: PromptList):
    """프롬프트 리스트를 큐에 추가하고 작업 ID를 반환하는 함수"""
    task_ids = []
    
    # INFO: 라우터 초기화 시 워커 생성 로직으로 변경
    if not hasattr(router, "worker_tasks"):
        router.worker_tasks = [
            asyncio.create_task(background_worker())
            for _ in range(NUM_WORKERS)
        ]
    
    for prompt in prompts.prompts:
        task_id = str(uuid.uuid4())
        # 큐에 작업 추가
        await task_queue.put((task_id, prompt))
        task_ids.append(task_id)

    return {"task_ids": task_ids, "status": "queued"}


@router.get("/tasks")
async def get_task_status(task_ids: str, request: Request):
    """작업 상태를 반환하는 함수"""
    # 쉼표로 구분된 작업 ID 리스트를 분리
    task_id_list = task_ids.split(",")
    res = {}

    for task_id in task_id_list:
        redis_client = request.app.state.redis_client
        task_data = await redis_client.hgetall(f"task:{task_id}")
        res[task_id] = task_data if task_data else {"status": "not_found"}
    
    return res
