from __future__ import annotations

import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)


class AiChatError(Exception):
    pass

SYSTEM_PROMPT = (
    "你是电子物料替代审核助手。只能从每条明细给出的候选 item_id 中选择，禁止编造候选之外的编号。"
    "判断该候选是否适合作为替代料。风险只能使用这些词：耐压、精度、功率、温度、封装、库存。"
    "只返回 JSON，对象格式为 "
    '{"results":[{"line_id":1,"picks":[{"item_id":2,"suitable":true,"reason":"理由","risks":["精度"]}]}]}'
)
ALLOWED_RISKS = {"耐压", "精度", "功率", "温度", "封装", "库存"}
BATCH_SIZE = 5


def suggest(
    lines: list[dict],
    *,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
) -> dict[int, list[dict] | None]:
    api_key = (api_key or "").strip()
    base_url = (base_url or "https://api.deepseek.com").rstrip("/")
    model = (model or "deepseek-chat").strip()
    if not api_key or not lines:
        return {}
    output: dict[int, list[dict] | None] = {}
    for offset in range(0, len(lines), BATCH_SIZE):
        chunk = lines[offset : offset + BATCH_SIZE]
        try:
            parsed = _request(chunk, api_key, base_url, model)
            output.update(_accept(chunk, parsed))
        except Exception:
            logger.warning("DeepSeek 批次失败，本批改用规则预筛", exc_info=True)
            for row in chunk:
                output[int(row["line_id"])] = None
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


def _request(chunk: list[dict], api_key: str, base_url: str, model: str) -> dict:
    response = httpx.post(
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
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _parse_json(content)


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
