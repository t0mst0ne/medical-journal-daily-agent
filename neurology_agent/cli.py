import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from .http import HttpClient
from .models import ReviewResult, RunStats
from .pmid import resolve_pmid
from .report import write_report
from .reviewers import Reviewer
from .sources import (
    discover_articles,
    discover_annals_neurology_articles,
    discover_jama_articles,
    discover_jama_podcasts,
    discover_lancet_articles,
    discover_lancet_neurology_articles,
    discover_nature_reviews_neurology_articles,
    discover_nejm_articles,
    discover_podcasts,
    discover_stroke_articles,
    download_pdf,
    enrich_article,
    enrich_jama_article,
    enrich_nejm_article,
    enrich_podcast,
    enrich_publisher_article,
)
from .state import State

JOURNALS = [
    "neurology",
    "jama-neurology",
    "nejm-neurology-neurosurgery",
    "lancet-neurology",
    "nature-reviews-neurology",
    "annals-neurology",
    "lancet",
    "stroke",
]


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--since", default="24h", help="all, last-run, or duration such as 24h/2d")
    parser.add_argument("--output", default="reports")
    parser.add_argument("--state", default=".neurology_agent_state.json")
    parser.add_argument("--provider", choices=["gemini", "openai", "claude"], default=None)
    parser.add_argument("--model")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--no-podcast", action="store_true")
    parser.add_argument("--pdf-dir", default="papers_pdf", help="directory for PMID_Journal_Topic-named full PDFs")
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument("--no-state", action="store_true")
    parser.add_argument("--no-email", action="store_true", help="email is disabled; kept for compatibility")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="neurology-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="collect publications and write a Markdown report")
    run.add_argument("--journal", choices=JOURNALS, default="neurology")
    _add_run_options(run)

    run_all = sub.add_parser("run-all", help="run every supported journal in one command")
    _add_run_options(run_all)

    return parser


def run(args) -> Path:
    load_dotenv()
    args.provider = args.provider or os.getenv("LLM_PROVIDER", "gemini")
    if args.provider not in {"gemini", "openai", "claude"}:
        raise ValueError("LLM_PROVIDER must be gemini, openai, or claude")
    args.model = args.model or os.getenv("LLM_MODEL")
    client = HttpClient()
    state = State(Path(args.state))
    stats = RunStats()
    if args.journal == "jama-neurology":
        publications = discover_jama_articles(client, args.since, state.last_run, args.limit)
    elif args.journal == "nejm-neurology-neurosurgery":
        publications = discover_nejm_articles(client, args.since, state.last_run, args.limit)
    elif args.journal == "lancet-neurology":
        publications = discover_lancet_neurology_articles(client, args.since, state.last_run, args.limit)
    elif args.journal == "nature-reviews-neurology":
        publications = discover_nature_reviews_neurology_articles(client, args.since, state.last_run, args.limit)
    elif args.journal == "annals-neurology":
        publications = discover_annals_neurology_articles(client, args.since, state.last_run, args.limit)
    elif args.journal == "lancet":
        publications = discover_lancet_articles(client, args.since, state.last_run, args.limit)
    elif args.journal == "stroke":
        publications = discover_stroke_articles(client, args.since, state.last_run, args.limit)
    else:
        publications = discover_articles(client, args.since, state.last_run, args.limit)
    if not args.no_podcast:
        if args.journal == "jama-neurology":
            publications += discover_jama_podcasts(client, args.since, state.last_run, args.limit)
        elif args.journal in {
            "nejm-neurology-neurosurgery",
            "lancet-neurology",
            "nature-reviews-neurology",
            "annals-neurology",
            "lancet",
            "stroke",
        }:
            publications += []
        else:
            publications += discover_podcasts(client, args.since, state.last_run, args.limit)
    stats.discovered = len(publications)
    reviewer = Reviewer(args.provider, args.model, client)
    results = []
    for item in publications:
        key = item.doi.lower() if item.doi else item.url
        if not args.no_state and state.seen(key):
            stats.skipped += 1
            continue
        try:
            if not item.is_podcast:
                if args.journal == "jama-neurology":
                    enrich_jama_article(client, item)
                elif args.journal == "nejm-neurology-neurosurgery":
                    enrich_nejm_article(client, item)
                elif args.journal in {
                    "lancet-neurology",
                    "nature-reviews-neurology",
                    "annals-neurology",
                    "lancet",
                    "stroke",
                }:
                    enrich_publisher_article(client, item)
                else:
                    enrich_article(client, item)
                resolve_pmid(client, item)
                if not args.no_pdf:
                    download_pdf(client, item, Path(args.pdf_dir))
            else:
                enrich_podcast(client, item)
            response = reviewer.review(item)
            result = ReviewResult(item, response.text, input_tokens=response.input_tokens, output_tokens=response.output_tokens)
            result.estimated_cost_usd = reviewer.cost(response.input_tokens, response.output_tokens)
            stats.processed += 1
            stats.input_tokens += response.input_tokens
            stats.output_tokens += response.output_tokens
            stats.estimated_cost_usd += result.estimated_cost_usd
        except Exception as exc:
            result = ReviewResult(item, error=str(exc))
            stats.errors.append(f"{item.title}: {exc}")
        results.append(result)
        if not args.no_state:
            state.mark(key)
    path = write_report(Path(args.output), results, stats, reviewer.provider, reviewer.model, journal=args.journal)
    if not args.no_state:
        state.save()
    return path


def run_all(args) -> list[Path]:
    paths = []
    for journal in JOURNALS:
        args.journal = journal
        try:
            paths.append(run(args))
        except Exception as exc:
            print(f"[{journal}] failed: {exc}")
    return paths


def main():
    args = build_parser().parse_args()
    if args.command == "run":
        print(run(args))
    elif args.command == "run-all":
        for path in run_all(args):
            print(path)
