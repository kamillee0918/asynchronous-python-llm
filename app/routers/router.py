from dotenv import load_dotenv
from fastapi import APIRouter, Request
from typing import List
from pydantic import BaseModel
from openai import AsyncOpenAI

import uuid
import os
import asyncio
import redis.asyncio as redis
import logging


# 로깅 설정
logging.basicConfig(level=logging.INFO) # INFO 레벨 설정
logger = logging.getLogger(__name__)

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
            await process_llm_task(task_id, prompt)
            task_queue.task_done()
        except Exception as error:
            print(f"Background worker error: {error}")
            continue


async def process_llm_task(task_id: str, prompt: str):
    """LLM 작업 처리 함수
    
    Args:
        task_id (str): 작업 ID
        prompt (str): 프롬프트
    """
    try:
        # Redis 상태를 "processing"으로 업데이트
        await redis_client.hset(
            f"task:{task_id}",
            mapping={
                "status": "processing",
                "progress": "0"
            }
        )

        # 24시간 TTL 설정(만료 시, 키 삭제)
        await redis_client.expire(
            f"task:{task_id}",
            86400
        )

        # OpenAI API 호출
        client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
        try:
            # OpenAI가 지원하는 모델 호출
            response = await client.responses.create(
                model="gpt-3.5-turbo",
                input=prompt,
                max_output_tokens=100, # 최대 출력 토큰 수
                temperature=0.7
            )

            result = response.output_text
        
            # 작업 결과 및 상태 업데이트
            await redis_client.hset(
                f"task:{task_id}",
                mapping={
                    "status": "completed",
                    "result": result,
                    "progress": "100"
                }
            )
        except TimeoutError:
            # 타임아웃 처리
            await redis_client.hset(
                f"task:{task_id}",
                mapping={
                    "status": "error",
                    "error": "Request timed out"
                }
            )
        except Exception as error:
            # OpenAI API 오류 처리
            await redis_client.hset(
                f"task:{task_id}",
                mapping={
                    "status": "error",
                    "error": str(error)
                }
            )
    except Exception as error:
        # 예상치 못한 오류 처리
        await redis_client.hset(
            f"task:{task_id}",
            mapping={
                "status": "unexpected_error",
                "error": str(error)
            }
        )


@router.post("/tasks")
async def create_tasks(prompts: PromptList):
    """프롬프트 리스트를 큐에 추가하고 작업 ID를 반환하는 함수
    
    Args:
        prompts (PromptList): 프롬프트 리스트
    
    Returns:
        dict: 작업 ID 리스트와 상태
    """
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
    """작업 상태를 반환하는 함수
    
    Args:
        task_ids (str): 쉼표로 구분된 작업 ID 리스트
        request (Request): FastAPI Request 객체
    
    Returns:
        dict: 작업 ID별 상태 정보
    """
    # 쉼표로 구분된 작업 ID 리스트를 분리
    task_id_list = task_ids.split(",")
    res = {}

    for task_id in task_id_list:
        redis_client = request.app.state.redis_client
        task_data = await redis_client.hgetall(f"task:{task_id}")
        res[task_id] = task_data if task_data else {"status": "not_found"}
    
    return res
