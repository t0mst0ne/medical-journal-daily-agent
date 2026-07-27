import json
import os
import urllib.request
from dataclasses import dataclass

from .http import HttpClient
from .models import Publication

ARTICLE_PROMPT = """請將以下英文 Abstract 完整翻譯成繁體中文。
只做忠實翻譯，不要摘要、改寫、評論、補充原文沒有的資訊，也不要提出治療建議。
保留原文段落結構、研究目的、方法、結果、數字、統計值、縮寫與不確定性。
若原文有小標題，請翻譯小標題並保留；只輸出翻譯內容，不要加「摘要」或其他前言。

文章標題：{title}
期刊：{journal}
DOI：{doi}
PMID（僅供參考，不需重複）：{pmid}
原文摘要或節錄：
{abstract}
"""

PODCAST_PROMPT = """請以繁體中文撰寫以下 Neurology Podcast 內容的忠實短介。
只根據提供的內容，分成「內容摘要」與「值得注意的臨床/研究訊息」兩段；若資料不足，請明確說明資料不足，不要臆測。

節目標題：{title}
內容：
{abstract}
"""


@dataclass
class ProviderResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class Reviewer:
    prices = {"gemini": (0.10, 0.40), "openai": (0.20, 1.25), "claude": (1.00, 5.00)}
    defaults = {"gemini": "gemini-2.5-flash-lite", "openai": "gpt-5.4-nano", "claude": "claude-haiku-4-5"}

    def __init__(self, provider: str, model: str | None, client: HttpClient):
        self.provider, self.model, self.client = provider, model or self.defaults[provider], client

    def prompt(self, item: Publication) -> str:
        template = PODCAST_PROMPT if item.is_podcast else ARTICLE_PROMPT
        return template.format(title=item.title, journal=item.journal, doi=item.doi or "未提供",
                               pmid=item.pmid or "未找到", abstract=item.abstract or "網站未提供 Abstract。")

    def review(self, item: Publication) -> ProviderResponse:
        prompt = self.prompt(item)
        if self.provider == "gemini":
            key = os.environ.get("GEMINI_API_KEY")
            if not key:
                raise RuntimeError("GEMINI_API_KEY is not set")
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            request = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={key}",
                data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode())
            usage = data.get("usageMetadata", {})
            return ProviderResponse(data["candidates"][0]["content"]["parts"][0]["text"],
                                    usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0))
        if self.provider == "openai":
            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("OPENAI_API_KEY is not set")
            data = self.client.post_json("https://api.openai.com/v1/responses", {"model": self.model, "input": prompt},
                                         {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            text = data.get("output_text", "") or "".join(part.get("text", "") for item in data.get("output", []) for part in item.get("content", []))
            usage = data.get("usage", {})
            return ProviderResponse(text, usage.get("input_tokens", 0), usage.get("output_tokens", 0))
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        data = self.client.post_json("https://api.anthropic.com/v1/messages",
                                     {"model": self.model, "max_tokens": 700, "messages": [{"role": "user", "content": prompt}]},
                                     {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
        usage = data.get("usage", {})
        return ProviderResponse("".join(x.get("text", "") for x in data.get("content", []) if x.get("type") == "text"),
                                usage.get("input_tokens", 0), usage.get("output_tokens", 0))

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        input_price, output_price = self.prices[self.provider]
        return input_tokens * input_price / 1_000_000 + output_tokens * output_price / 1_000_000
