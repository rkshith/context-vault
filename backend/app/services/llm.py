"""LLM access through OpenRouter.

OpenRouter exposes an OpenAI-compatible API, so the official openai client
is pointed at the OpenRouter base URL with our API key.
"""

from openai import AsyncOpenAI

from app.core.config import get_settings

settings = get_settings()

_client: AsyncOpenAI | None = None

HISTORY_MESSAGES = 8

SYSTEM_PROMPT = (
    "You are a document intelligence assistant. Answer the user's question using "
    "ONLY the numbered context passages provided, which are excerpts from the "
    "user's own documents.\n"
    "Rules:\n"
    "- Cite passages inline using their numbers, e.g. [1] or [2][3].\n"
    "- If the context is insufficient to answer, say so plainly and do not invent facts.\n"
    "- Be concise and clear. Use markdown formatting where it helps."
)


class LLMNotConfigured(Exception):
    pass


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.openrouter_api_key:
            raise LLMNotConfigured("OPENROUTER_API_KEY is not set")
        _client = AsyncOpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            default_headers={
                "HTTP-Referer": settings.frontend_origin,
                "X-Title": settings.app_name,
            },
        )
    return _client


def build_context(passages: list[tuple[str, int, str]]) -> str:
    """passages: (filename, page_number, text), already in ranking order."""
    blocks = [
        f"[{index}] {filename} (page {page_number})\n{text}"
        for index, (filename, page_number, text) in enumerate(passages, start=1)
    ]
    return "\n\n".join(blocks)


async def generate_answer(
    question: str,
    passages: list[tuple[str, int, str]],
    history: list[dict],
) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    messages.append(
        {
            "role": "user",
            "content": f"Context passages:\n\n{build_context(passages)}\n\nQuestion: {question}",
        }
    )

    response = await get_client().chat.completions.create(
        model=settings.openrouter_model,
        messages=messages,
        temperature=0.2,
        max_tokens=1024,
    )

    answer = response.choices[0].message.content
    if not answer:
        raise RuntimeError("LLM returned an empty response")
    return answer.strip()


async def stream_answer(question: str, passages: list[tuple[str, int, str]], history: list[dict]):
    """Yield answer tokens as they arrive (SSE-friendly async generator)."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    messages.append(
        {
            "role": "user",
            "content": f"Context passages:\n\n{build_context(passages)}\n\nQuestion: {question}",
        }
    )

    stream = await get_client().chat.completions.create(
        model=settings.openrouter_model,
        messages=messages,
        temperature=0.2,
        max_tokens=1024,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta
