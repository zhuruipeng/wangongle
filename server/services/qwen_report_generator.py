from openai import OpenAI

from ..prompts.service_report_prompt import SYSTEM_PROMPT, build_user_prompt
from ..settings import AiReportSettings


def request_qwen_report(service_type: str, transcript: str, settings: AiReportSettings) -> str:
    client = OpenAI(api_key=settings.api_key, base_url=settings.base_url, timeout=settings.timeout_seconds)
    completion = client.chat.completions.create(
        model=settings.model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(service_type, transcript)},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        extra_body={"enable_thinking": False},
    )
    return completion.choices[0].message.content or ""
