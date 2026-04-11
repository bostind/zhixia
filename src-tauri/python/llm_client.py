import os
from openai import OpenAI, APITimeoutError, APIConnectionError
import config
from config import get_logger

logger = get_logger(__name__)


class LLMError(Exception):
    """LLM 调用失败的自定义异常。"""
    pass


_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        kwargs = {"api_key": config.LLM_API_KEY}
        if config.LLM_BASE_URL:
            kwargs["base_url"] = config.LLM_BASE_URL
        _client = OpenAI(**kwargs)
    return _client


def chat_completion(system_prompt: str, user_prompt: str, temperature: float = 0.3, model: str | None = None) -> str:
    """调用云端 LLM，返回文本内容。"""
    client = get_client()
    try:
        response = client.chat.completions.create(
            model=model or config.LLM_QUERY_MODEL or config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            timeout=45,
        )
        return response.choices[0].message.content.strip()
    except APITimeoutError as e:
        logger.warning("LLM API timeout: %s", e)
        raise LLMError(f"LLM API timeout: {e}")
    except APIConnectionError as e:
        logger.warning("LLM API connection error: %s", e)
        raise LLMError(f"LLM API connection error: {e}")
    except Exception as e:
        logger.exception("LLM API error")
        raise LLMError(f"LLM API error: {e}")
