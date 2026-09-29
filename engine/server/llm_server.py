import os
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from openai import AsyncOpenAI, OpenAI

log = logging.getLogger("jarvis.llm_server")

_llm_client = None
_embed_client = None
_USAGE_FILE = Path(__file__).parent.parent.parent / "data" / "usage_log.jsonl"


def _is_bonsai() -> bool:
    # Bonsai (Qwen3.8 base): dùng thẻ <think> như Qwen, tham số thinking riêng.
    return os.getenv("BONSAI_MODEL", "false").lower() == "true"


def _is_gemma() -> bool:
    # BONSAI_MODEL ưu tiên hơn CHANG_MODEL để bật thử Bonsai mà không phải tắt cờ Gemma.
    return os.getenv("CHANG_MODEL", "false").lower() == "true" and not _is_bonsai()


# ---------------------------------------------------------------------------
# Model adapter: tham số + cú pháp function-calling theo từng hãng, một chỗ duy
# nhất. Đổi model (Qwen/Gemma/Bonsai) chỉ đổi cờ .env, hành vi theo đúng spec
# đã đo (live_eval: Qwen gate 52/54 + classifier 32/32, Gemma gate 70/70).
# Số liệu bên dưới giữ nguyên hành vi cũ — refactor cấu trúc, không đổi số.
# ---------------------------------------------------------------------------
MODEL_PROFILES = {
    # Qwen3.5 (kể cả bản coder đang phục vụ): vendor spec qua llama.cpp
    # OpenAI-compatible endpoint. Đã probe: server có jinja tool template,
    # tool_choice auto/required đều trả native tool_calls (không cần parse text).
    "qwen": {
        "temp_thinking": 1.0, "temp_instruct": 0.7,
        "top_p_thinking": 0.95, "top_p_instruct": 0.8,
        "top_k": 20, "min_p_thinking": 0.5, "min_p_instruct": 0.0,
        "presence_thinking": 1.5, "presence_instruct": 1.5,
        "repetition_penalty": 1.0,
        "max_thinking": 16384, "max_instruct": 8192,
        "think_start": "<think>", "think_end": "</think>",
        "think_inject": None,  # Qwen tự bật thinking theo template, không chèn token
        "merge_system_first": True,  # template Qwen/Bonsai bắt system đứng đầu
        "native_tools": True,
    },
    # Bonsai 2 27B (ternary): model card khuyến nghị thinking min_p=0.0,
    # presence_penalty=0.0. Nhánh instruct giữ presence 1.5 như hành vi cũ.
    "bonsai": {
        "temp_thinking": 1.0, "temp_instruct": 0.7,
        "top_p_thinking": 0.95, "top_p_instruct": 0.8,
        "top_k": 20, "min_p_thinking": 0.0, "min_p_instruct": 0.0,
        "presence_thinking": 0.0, "presence_instruct": 1.5,
        "repetition_penalty": 1.0,
        "max_thinking": 16384, "max_instruct": 8192,
        "think_start": "<think>", "think_end": "</think>",
        "think_inject": None,
        "merge_system_first": True,
        "native_tools": True,
    },
    # Gemma 4: custom config, thinking kích bằng token <|think|> + reasoning flag.
    "gemma": {
        "temp_thinking": 1.0, "temp_instruct": 0.4,
        "top_p_thinking": 0.95, "top_p_instruct": 0.8,
        "top_k": 40, "min_p_thinking": 0.5, "min_p_instruct": 0.0,
        "presence_thinking": 0.0, "presence_instruct": 0.0,
        "repetition_penalty": None,
        "max_thinking": 16384, "max_instruct": 8192,
        "think_start": "<|channel>thought", "think_end": "<channel|>",
        "think_inject": "<|think|>",
        "merge_system_first": False,  # Gemma chịu được system giữa hội thoại
        "native_tools": True,
    },
}


def active_model_key() -> str:
    """'bonsai' | 'gemma' | 'qwen' theo cờ .env (bonsai > gemma > qwen)."""
    if _is_bonsai():
        return "bonsai"
    if _is_gemma():
        return "gemma"
    return "qwen"


def active_model_profile() -> dict:
    return MODEL_PROFILES[active_model_key()]


def active_model_name() -> str | None:
    """Tên model chat đang chạy. Cùng quy tắc chọn với get_llm_client (bonsai > gemma > qwen)."""
    if _is_bonsai():
        return os.getenv("LOCAL_BONSAI_MODEL")
    if _is_gemma():
        return os.getenv("LOCAL_GEMMA_MODEL")
    return os.getenv("LOCAL_MODEL")


def vision_model_name() -> str | None:
    """Model 'mắt' cho screen/webcam/OCR: đi theo model đang chạy khi VISION_MODEL trống hoặc 'auto',
    để đổi model chat thì vision đổi theo, không phải sửa hai chỗ."""
    v = (os.getenv("VISION_MODEL") or "").strip()
    return active_model_name() if not v or v.lower() == "auto" else v


def vision_request_kwargs() -> dict:
    """Tham số cho request vision/OCR (chế độ instruct, tắt thinking) theo model đang chạy.
    Trùng giá trị nhánh instruct của call_llm; tách riêng để không đụng call_llm (nhiều phụ thuộc)."""
    gemma = _is_gemma()
    return {
        "temperature": 0.4 if gemma else 0.7,
        "top_p": 0.8,
        "presence_penalty": 0.0 if gemma else 1.5,
        "extra_body": {
            "top_k": 40 if gemma else 20,
            "min_p": 0.0,
            "reasoning": "off",
            "chat_template_kwargs": {"enable_thinking": False},
        },
    }


def _log_usage(in_tokens: int, out_tokens: int, call_type: str = "api", cached_tokens: int = 0):
    in_t = in_tokens or 0
    out_t = out_tokens or 0
    c_t = cached_tokens or 0
    log.info("[%s] tokens: in=%d (cached=%d) out=%d total=%d", call_type, in_t, c_t, out_t, in_t + out_t)
    try:
        _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "type": call_type,
            "input_tokens": in_t,
            "cached_tokens": c_t,
            "output_tokens": out_t,
        }
        with open(_USAGE_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        log.warning("Failed to write usage JSONL: %s", e)


# ---------------------------------------------------------------------------
# OpenAI client (cached)
# ---------------------------------------------------------------------------

def get_llm_client():
    global _llm_client
    if _llm_client is None:
        api_key = os.getenv("LOCAL_API_KEY")
        base_url = os.getenv("LOCAL_URL")
        
        # Check model switch config
        if _is_bonsai():
            model = os.getenv("LOCAL_BONSAI_MODEL")
            log.info("Switching LLM client model to Bonsai: %s", model)
        elif _is_gemma():
            model = os.getenv("LOCAL_GEMMA_MODEL")
            log.info("Switching LLM client model to Gemma 4: %s", model)
        else:
            model = os.getenv("LOCAL_MODEL")
            
        # Không có timeout tường minh trước đây -> mặc định SDK ~600s. Nếu
        # llama.cpp treo hoặc quá tải, call_llm (dùng bởi routing, agents và
        # luồng phản hồi chính) có thể chặn tới 10 phút trước khi bất kỳ
        # fallback nào kích hoạt, trong khi người dùng chỉ thấy "đang nghĩ"
        # không phản hồi suốt thời gian đó.
        llm_timeout = float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "180"))
        _llm_client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=llm_timeout)
        _llm_client.model = model
    return _llm_client


def get_embed_client():
    global _embed_client
    if _embed_client is None:
        api_key = os.getenv("LOCAL_EMBED_API")
        base_url = os.getenv("LOCAL_EMBED_URL")
        if not api_key or not base_url:
            return None
        embed_timeout = float(os.getenv("LOCAL_EMBED_TIMEOUT_SECONDS", "30"))
        _embed_client = OpenAI(api_key=api_key, base_url=base_url, timeout=embed_timeout)
        log.info("Initialized lazy embedding client pointing to %s", base_url)
    return _embed_client


def reset_llm_client():
    global _llm_client
    _llm_client = None


async def close_llm_client():
    """Close and clear the shared LLM client during application shutdown."""
    global _llm_client
    try:
        if _llm_client is not None:
            await _llm_client.close()
    finally:
        _llm_client = None

# ---------------------------------------------------------------------------
# Thinking‑tag stripper for Qwen and Gemma 4 <think> / <|channel>thought blocks
# ---------------------------------------------------------------------------

class StreamThinkStripper:
    def __init__(self):
        prof = active_model_profile()
        self.START = prof["think_start"]
        self.END   = prof["think_end"]
            
        self.buffer = ""
        self.suppress = False
        self.just_ended = False

    def _partial_prefix(self, haystack: str, prefix: str):
        if not prefix:
            return False
        for i in range(1, min(len(prefix), len(haystack)) + 1):
            if prefix.startswith(haystack[-i:]):
                return True
        return False

    def process(self, text: str) -> str:
        if not text:
            return ""
        self.buffer += text
        out = ""

        while self.buffer:
            if self.suppress:
                idx = self.buffer.find(self.END)
                if idx != -1:
                    self.buffer = self.buffer[idx + len(self.END):]
                    self.suppress = False
                    self.just_ended = True
                elif self._partial_prefix(self.buffer, self.END):
                    break
                else:
                    self.buffer = ""
                    break
                continue

            ti = self.buffer.find(self.START)
            if ti != -1:
                out += self.buffer[:ti]
                self.buffer = self.buffer[ti + len(self.START):]
                self.suppress = True
            else:
                if self._partial_prefix(self.buffer, self.START):
                    break
                
                # Nếu vừa mới kết thúc thẻ đóng, lọc bỏ mọi khoảng trắng/dấu xuống dòng thừa ở đầu
                if self.just_ended:
                    stripped_buf = self.buffer.lstrip()
                    if not stripped_buf and self.buffer:
                        break
                    self.buffer = stripped_buf
                    self.just_ended = False
                    
                out += self.buffer
                self.buffer = ""

        return out


def strip_think(content: str) -> str:
    if not content:
        return content
    start = active_model_profile()["think_start"]
    if active_model_key() == "gemma":
        # Thẻ đóng thật là "<channel|>"; bản cũ viết "</channel|>" khiến "|" thành toán tử "hoặc"
        # của regex và xoá mọi ký tự ">" khỏi câu trả lời.
        content = re.sub(r'<\|channel>thought.*?<channel\|>', '', content, flags=re.DOTALL)
        if start in content:
            content = content.split(start)[0]
    else:
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
        if start in content:
            content = content.split(start)[0]
    return content.strip()


# ---------------------------------------------------------------------------
# Core LLM call compliant with Qwen3.5-9B and Gemma 4 official specifications
# ---------------------------------------------------------------------------

async def call_llm(
    messages: list,
    model: str = None,
    thinking: bool = False,
    stream: bool = False,
    tools: list = None,
    tool_choice: str = None,
    temperature: float = None,
    max_tokens: int = None,
    response_format: dict = None
):
    # Single choke point for every LLM caller in the process — hot path,
    # agents, Dream, Learning, Self-Healing, Evolution, RAG. Admission control
    # lives here so background work cannot queue in front of a live turn.
    from engine.core.activity_gate import get_inference_gate, in_interactive_turn
    async with get_inference_gate().slot(interactive=in_interactive_turn()):
        return await _call_llm_inner(
            messages, model, thinking, stream, tools, tool_choice,
            temperature, max_tokens, response_format,
        )


async def _call_llm_inner(
    messages: list,
    model: str = None,
    thinking: bool = False,
    stream: bool = False,
    tools: list = None,
    tool_choice: str = None,
    temperature: float = None,
    max_tokens: int = None,
    response_format: dict = None
):
    client = get_llm_client()
    model_name = model or client.model
    prof = active_model_profile()

    cleaned = []
    if messages:
        for msg in messages:
            if not isinstance(msg, dict):
                if hasattr(msg, "model_dump"):
                    msg_dict = msg.model_dump()
                elif hasattr(msg, "dict"):
                    msg_dict = msg.dict()
                else:
                    msg_dict = {
                        "role": getattr(msg, "role", "assistant"),
                        "content": getattr(msg, "content", ""),
                    }
                    if hasattr(msg, "tool_calls"):
                        msg_dict["tool_calls"] = getattr(msg, "tool_calls", None)
                msg = msg_dict

            role = msg.get("role")
            content = msg.get("content")
            if role == "assistant" and isinstance(content, str):
                cleaned.append({**msg, "content": strip_think(content)})
            else:
                cleaned.append(msg)

    # Template Qwen/Bonsai raise "System message must be at the beginning" nếu có
    # system message không nằm đầu (Jarvis chèn context giữa hội thoại). Gemma chịu được.
    if prof["merge_system_first"] and any(m.get("role") == "system" for m in cleaned[1:]):
        sys_parts = [str(m.get("content") or "") for m in cleaned if m.get("role") == "system"]
        rest = [m for m in cleaned if m.get("role") != "system"]
        cleaned = [{"role": "system", "content": "\n\n".join(p for p in sys_parts if p)}] + rest

    # 1. Khởi tạo extra_body chứa các tham số riêng theo profile hãng
    extra_body = {"top_k": prof["top_k"]}
    if prof["repetition_penalty"] is not None:
        extra_body["repetition_penalty"] = prof["repetition_penalty"]

    # 2. Xây dựng tham số chuẩn và mở rộng dựa trên mode (Thinking hay Instruct)
    mode = "thinking" if thinking else "instruct"
    temp = prof[f"temp_{mode}"] if temperature is None else temperature
    top_p = prof[f"top_p_{mode}"]
    presence_penalty = prof[f"presence_{mode}"]
    default_max_tokens = prof[f"max_{mode}"]
    extra_body.update({
        "min_p": prof[f"min_p_{mode}"],
        "reasoning": "on" if thinking else "off",
        "chat_template_kwargs": {"enable_thinking": thinking},
    })

    if thinking and prof["think_inject"]:
        # Gemma 4 triggers thinking with <|think|> in system prompt,
        # or with specific reasoning control variables on llama.cpp.
        has_system = False
        for msg in cleaned:
            if msg.get("role") == "system":
                has_system = True
                sys_content = msg.get("content", "")
                if sys_content and prof["think_inject"] not in sys_content:
                    msg["content"] = prof["think_inject"] + "\n" + sys_content
                break
        if not has_system:
            cleaned.insert(0, {"role": "system", "content": prof["think_inject"]})

    # 3. Đóng gói tham số gửi đi
    params = {
        "model": model_name,
        "messages": cleaned,
        "temperature": temp,
        "top_p": top_p,
        "max_tokens": max_tokens if max_tokens is not None else default_max_tokens,
        "presence_penalty": presence_penalty,
        "extra_body": extra_body,
        "stream": stream,
    }

    if tools is not None:
        params["tools"] = tools
    if tool_choice is not None:
        params["tool_choice"] = tool_choice
    if response_format is not None:
        params["response_format"] = response_format

    if stream:
        params["stream_options"] = {"include_usage": True}

    log.info(
        "LLM request config: model=%s thinking=%s stream=%s temperature=%s top_p=%s top_k=%s min_p=%s max_tokens=%s",
        model_name,
        thinking,
        stream,
        temp,
        top_p,
        extra_body.get("top_k"),
        extra_body.get("min_p"),
        params["max_tokens"],
    )

    request_started = time.monotonic()
    try:
        response = await client.chat.completions.create(**params)
        log.info(
            "LLM transport ready: stream=%s elapsed=%.2fs",
            stream,
            time.monotonic() - request_started,
        )

        if stream:
            async def stream_wrapper(original_stream):
                stripper = StreamThinkStripper()
                last_usage = None
                async for chunk in original_stream:
                    if not chunk.choices:
                        if hasattr(chunk, "usage") and chunk.usage:
                            last_usage = chunk.usage
                        yield chunk
                        continue
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        delta.content = stripper.process(delta.content)
                    yield chunk
                if last_usage:
                    cached_t = 0
                    if hasattr(last_usage, "prompt_tokens_details") and last_usage.prompt_tokens_details:
                        cached_t = getattr(last_usage.prompt_tokens_details, "cached_tokens", 0) or 0
                    _log_usage(last_usage.prompt_tokens, last_usage.completion_tokens, cached_tokens=cached_t)

            return stream_wrapper(response)
        else:
            if hasattr(response, "usage") and response.usage:
                usage = response.usage
                cached_t = 0
                if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                    cached_t = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
                _log_usage(usage.prompt_tokens, usage.completion_tokens, cached_tokens=cached_t)
            msg = response.choices[0].message if response.choices else None
            if msg and msg.content:
                msg.content = strip_think(msg.content)
            return response

    except Exception as e:
        log.error(
            "LLM API call failed after %.2fs: %s: %s",
            time.monotonic() - request_started,
            type(e).__name__,
            e,
            exc_info=True,
        )
        raise
