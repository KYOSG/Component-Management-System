from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

logger = logging.getLogger(__name__)


class AiChatError(Exception):
    pass


class AiCancelled(Exception):
    pass


class AiRun:
    def __init__(self) -> None:
        self.cancel = threading.Event()
        self.client: httpx.Client | None = None
        self.pool: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()

    def stop(self) -> None:
        with self._lock:
            self.cancel.set()
            client = self.client
            pool = self.pool
            self.client = None
            self.pool = None
        if client is not None:
            client.close()
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    def finish(self) -> None:
        with self._lock:
            if self.cancel.is_set():
                return
            client = self.client
            pool = self.pool
            self.client = None
            self.pool = None
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=False)
        if client is not None:
            client.close()

SYSTEM_PROMPT = (
    "你是电子物料替代审核助手。\n"
    "规则：\n"
    "1. 候选物料已经过封装兼容性预筛，封装兼容是默认前提，严禁将「封装相同」作为推荐理由。\n"
    "2. 判断替代适用性，必须依据电气参数：耐压值是否 ≥ BOM 需求、精度误差是否符合设计、功率是否 ≥ 需求、工作温度范围是否覆盖等。\n"
    "3. reason 要具体说明关键参数对比，例如：「AO3400A 为 N沟道 MOSFET，Vdss 30V 低于原始 60V，适合低压小信号开关场合，需确认电路电压余量」。\n"
    "4. 只能从给出的 candidates item_id 中选择，禁止编造。\n"
    "5. 只返回确实可以替换的候选。不合适的不要写入 picks。\n"
    "6. risks 只能使用：耐压、精度、功率、温度、封装、库存。\n"
    "7. 只返回 JSON："
    '{"results":[{"line_id":1,"picks":[{"item_id":2,"suitable":true,"reason":"理由","risks":["耐压"]}]}]}'
)
ALLOWED_RISKS = {"耐压", "精度", "功率", "温度", "封装", "库存"}
BATCH_SIZE = 1
READ_TIMEOUT = 30.0


def suggest(
    lines: list[dict],
    *,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    run: AiRun | None = None,
    on_batch: Callable[[dict[int, list[dict] | None]], None] | None = None,
) -> dict[int, list[dict] | None]:
    api_key = (api_key or "").strip()
    base_url = (base_url or "https://api.deepseek.com").rstrip("/")
    model = (model or "deepseek-chat").strip()
    if not api_key or not lines or (run is not None and run.cancel.is_set()):
        return {}
    client = httpx.Client(timeout=httpx.Timeout(READ_TIMEOUT, connect=10.0), trust_env=False)
    pool = ThreadPoolExecutor(max_workers=min(2, len(lines)))
    if run is not None:
        run.client = client
        run.pool = pool
        if run.cancel.is_set():
            run.client = None
            run.pool = None
            client.close()
            pool.shutdown(wait=False, cancel_futures=True)
            return {}
    chunks = [lines[offset : offset + BATCH_SIZE] for offset in range(0, len(lines), BATCH_SIZE)]
    output: dict[int, list[dict] | None] = {}
    futures = {pool.submit(_request, chunk, api_key, base_url, model, client, run): chunk for chunk in chunks}
    try:
        for future in as_completed(futures):
            if run is not None and run.cancel.is_set():
                break
            chunk = futures[future]
            try:
                accepted = _accept(chunk, future.result())
            except AiCancelled:
                break
            except Exception as exc:
                if run is not None and run.cancel.is_set():
                    break
                logger.warning("DeepSeek 批次失败，本批不给出替换建议：%s", exc)
                accepted = {int(row["line_id"]): None for row in chunk}
            output.update(accepted)
            if on_batch is not None:
                on_batch(accepted)
    finally:
        if run is None:
            pool.shutdown(wait=True, cancel_futures=False)
            client.close()
        else:
            run.finish()
    return output


def chat(prompt: str, *, api_key: str, base_url: str, model: str) -> str:
    api_key = (api_key or "").strip()
    base_url = (base_url or "https://api.deepseek.com").rstrip("/")
    model = (model or "deepseek-chat").strip()
    if not api_key:
        raise AiChatError("请先填写 API Key")
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            },
            timeout=60,
            trust_env=False,
        )
    except httpx.RequestError as exc:
        raise AiChatError(f"无法连接接口：{exc}") from exc
    if response.status_code >= 400:
        raise AiChatError(_error_detail(response))
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AiChatError("接口返回的内容无法解析") from exc
    if not isinstance(content, str) or not content.strip():
        raise AiChatError("模型没有返回文本")
    return content


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = (response.text or "").strip()
        return text[:200] or f"接口返回 {response.status_code}"
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])[:300]
    return f"接口返回 {response.status_code}"


def _request(
    chunk: list[dict],
    api_key: str,
    base_url: str,
    model: str,
    client: httpx.Client,
    run: AiRun | None,
) -> dict:
    last_error: Exception | None = None
    for attempt in (1, 2):
        if run is not None and run.cancel.is_set():
            raise AiCancelled()
        try:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps({"lines": chunk}, ensure_ascii=False)},
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return _parse_json(content)
        except AiCancelled:
            raise
        except Exception as exc:
            if run is not None and run.cancel.is_set():
                raise AiCancelled() from exc
            if not isinstance(exc, httpx.TimeoutException):
                raise
            last_error = exc
            logger.warning("DeepSeek 读取超时，第 %s 次：%s", attempt, exc)
    assert last_error is not None
    raise last_error


def _parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("DeepSeek 返回的不是 JSON 对象")
    return data


def _accept(chunk: list[dict], data: dict) -> dict[int, list[dict] | None]:
    results = data.get("results")
    if not isinstance(results, list):
        raise ValueError("DeepSeek 返回缺少 results")
    by_line = {}
    for row in results:
        if isinstance(row, dict) and row.get("line_id") is not None:
            by_line[int(row["line_id"])] = row
    allowed = {int(row["line_id"]): {int(item["item_id"]) for item in row["candidates"]} for row in chunk}
    output: dict[int, list[dict] | None] = {}
    for row in chunk:
        line_id = int(row["line_id"])
        found = by_line.get(line_id)
        picks: list[dict] = []
        if isinstance(found, dict):
            for pick in found.get("picks") or []:
                if not isinstance(pick, dict) or not pick.get("suitable"):
                    continue
                try:
                    item_id = int(pick.get("item_id"))
                except (TypeError, ValueError):
                    continue
                if item_id not in allowed[line_id]:
                    continue
                risks = [risk for risk in (pick.get("risks") or []) if risk in ALLOWED_RISKS]
                picks.append(
                    {
                        "item_id": item_id,
                        "suitable": True,
                        "reason": str(pick.get("reason") or "").strip(),
                        "risks": risks,
                    }
                )
        output[line_id] = picks
    return output
