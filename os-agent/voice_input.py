import base64
from typing import Optional

from openai import OpenAI

from config import QWEN_API_BASE, QWEN_API_KEY, QWEN_ASR_MODEL


def build_audio_data_url(audio_bytes: bytes, mime_type: str = "audio/wav") -> str:
    encoded_audio = base64.b64encode(audio_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded_audio}"


def _extract_transcript_text(response) -> str:
    choices = getattr(response, "choices", None) or []
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict):
                    text_value = item.get("text") or item.get("transcript") or ""
                else:
                    text_value = getattr(item, "text", None) or getattr(item, "transcript", None) or ""
                if text_value:
                    text_parts.append(str(text_value).strip())
            if text_parts:
                return "\n".join(part for part in text_parts if part)

    text = getattr(response, "text", "") or ""
    if text:
        return text.strip()

    if hasattr(response, "output_text") and response.output_text:
        return str(response.output_text).strip()

    output = getattr(response, "output", None)
    if not output:
        return ""

    for item in output:
        for content in getattr(item, "content", []) or []:
            transcript = getattr(content, "transcript", None)
            if transcript:
                return str(transcript).strip()
            text_value = getattr(content, "text", None)
            if text_value:
                return str(text_value).strip()
    return ""


def transcribe_audio_bytes(
    audio_bytes: bytes,
    mime_type: str = "audio/wav",
    client: Optional[OpenAI] = None,
    model: Optional[str] = None,
) -> str:
    if not audio_bytes:
        raise ValueError("录音数据为空，无法识别。")

    asr_client = client or OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_API_BASE)
    asr_model = model or QWEN_ASR_MODEL

    # 按阿里云百炼 Qwen-ASR 官方 OpenAI 兼容写法调用：
    # POST /compatible-mode/v1/chat/completions + input_audio
    try:
        response = asr_client.chat.completions.create(
            model=asr_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": build_audio_data_url(audio_bytes, mime_type=mime_type),
                            },
                        }
                    ],
                }
            ],
            stream=False,
            extra_body={
                "asr_options": {
                    "enable_itn": False,
                }
            },
        )
    except Exception as exc:
        error_text = str(exc)
        if "404" in error_text:
            raise RuntimeError(
                "语音识别接口返回 404。请检查 QWEN_API_BASE 是否为百炼兼容模式地址，"
                f"并确认语音模型 `{asr_model}` 在当前账号和地域可用。原始错误：{error_text}"
            ) from exc
        raise RuntimeError(f"语音识别请求失败：{error_text}") from exc

    transcript = _extract_transcript_text(response)

    if not transcript:
        raise RuntimeError("语音识别未返回文本结果。")
    return transcript



