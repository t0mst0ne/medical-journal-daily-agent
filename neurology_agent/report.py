from datetime import datetime
from pathlib import Path

from .models import ReviewResult, RunStats


def _render(result: ReviewResult) -> str:
    item = result.publication
    if item.is_podcast:
        audio = f"\n**音訊連結**: {item.audio_url}" if item.audio_url else ""
        return f"## Podcast: {item.title}\n\n**原文標題**: {item.title}\n**發布日期**: {item.published or '未提供'}\n**連結**: {item.url}{audio}\n\n**內容摘要**:\n\n{result.review or '未產生摘要。'}\n"
    pdf = f"\n**Full PDF**: {item.pdf_url}" if item.pdf_url else "\n**Full PDF**: 未找到"
    if item.local_pdf:
        local_pdf = f"\n**本地 PDF**: `{item.local_pdf}`"
    elif item.pdf_url:
        local_pdf = "\n**本地 PDF**: 未下載（可能需要期刊訂閱或登入權限）"
    else:
        local_pdf = ""
    return f"## {item.title}\n\n**期刊**: {item.journal}\n**原文標題**: {item.title}\n**DOI**: {item.doi or '未提供'}\n**PMID**: {item.pmid or '未找到'}（來源：{item.pmid_source}）\n**發布日期**: {item.published or '未提供'}\n**文章連結**: {item.url}{pdf}{local_pdf}\n\n**Abstract 繁體中文翻譯**:\n\n{result.review or '未產生翻譯。'}\n"


def write_report(
    output_dir: Path,
    results: list[ReviewResult],
    stats: RunStats,
    provider: str,
    model: str,
    journal: str = "neurology",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    labels = {
        "neurology": "Neurology",
        "jama-neurology": "JAMA Neurology",
        "nejm-neurology-neurosurgery": "NEJM Neurology/Neurosurgery",
        "lancet-neurology": "The Lancet Neurology",
        "nature-reviews-neurology": "Nature Reviews Neurology",
        "annals-neurology": "Annals of Neurology",
        "lancet": "The Lancet",
        "stroke": "Stroke",
    }
    label = labels.get(journal, journal)
    slug = journal
    path = output_dir / f"{datetime.now().date().isoformat()}-{slug}-daily.md"
    lines = [f"# {label} 每日文獻導讀 - {datetime.now().date().isoformat()}", "",
             f"- 摘要模型：`{provider}/{model}`",
             f"- 發現：{stats.discovered} 篇，完成：{stats.processed} 篇，略過：{stats.skipped} 篇",
             f"- Token：輸入 {stats.input_tokens}，輸出 {stats.output_tokens}，估算費用 ${stats.estimated_cost_usd:.6f}", ""]
    if stats.errors:
        lines += ["## 執行錯誤", "", *[f"- {error}" for error in stats.errors], ""]
    lines += [_render(result) for result in results]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
