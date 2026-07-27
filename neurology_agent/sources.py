import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urljoin

import feedparser
from bs4 import BeautifulSoup

from .http import HttpClient
from .models import Publication

RSS_URL = (
    "https://www.neurology.org/action/showFeed?ui=0&mi=4v9whj&type=search&feed=rss&query="
    "%2526content%253Darticles%2526publication%253Dwnl%2526publication%253Dcpj%2526publication%253Dne9%2526"
    "publication%253Dnxg%2526publication%253Dnxi%2526publication%253Dwn9%2526sortBy%253DEarliest%2526target%253Ddefault"
)
ALL_ARTICLES_URL = "https://www.neurology.org/all-articles"
PODCAST_URL = "https://www.neurology.org/podcast"
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.I)

JAMA_NEUROLOGY_FEEDS = [
    "https://jamanetwork.com/rss/site_16/onlineFirst_72.xml",
    "https://jamanetwork.com/rss/site_16/72.xml",
]
JAMA_NEUROLOGY_PODCAST_FEED = "https://jamaneurologyauthorinterviews.libsyn.com/rss"
JAMA_NEUROLOGY_HOME = "https://jamanetwork.com/journals/jamaneurology"
NEJM_NEUROLOGY_FEED = "https://onesearch-rss.nejm.org/api/specialty/rss?context=nejm&specialty=neurology-neurosurgery"
NEJM_HOME = "https://www.nejm.org"
LANCET_NEUROLOGY_FEED = "https://www.thelancet.com/rssfeed/laneur_current.xml"
LANCET_NEUROLOGY_HOME = "https://www.thelancet.com"
LANCET_FEED = "https://www.thelancet.com/rssfeed/lancet_current.xml"
LANCET_HOME = "https://www.thelancet.com"
NATURE_REVIEWS_NEUROLOGY_FEED = "https://www.nature.com/nrneurol.rss"
ANNALS_NEUROLOGY_FEED = "https://onlinelibrary.wiley.com/action/showFeed?jc=15318249&type=etoc&feed=rss"
STROKE_FEED = "https://www.ahajournals.org/action/showFeed?jc=str&type=etoc&feed=rss"
STROKE_HOME = "https://www.ahajournals.org"


def normalize_doi(value: str) -> str:
    doi = value.strip().split("?", 1)[0].rstrip(".,);]'\"")
    return re.sub(r"^https?://doi.org/", "", doi, flags=re.I)


def _is_supplement_pdf(url: str) -> bool:
    value = (url or "").lower()
    return any(marker in value for marker in (
        "/doi/suppl/",
        "/suppl_file/",
        "supplemental",
        "supplementary",
        "suppinfo",
        "supinfo",
    ))


def _main_pdf_url(soup: BeautifulSoup, base_url: str) -> str | None:
    # Query each selector separately: comma-separated selectors return the
    # first match in document order, which may be a supplement link.
    for selector in (
        "meta[name='citation_pdf_url']",
        "link[type='application/pdf']",
        "a[href*='/doi/pdf/']",
        "a[href*='/doi/epdf/']",
        "a[href*='/doi/epub/']",
    ):
        for node in soup.select(selector):
            candidate = urljoin(base_url, node.get("content") or node.get("href") or "")
            if candidate and not _is_supplement_pdf(candidate):
                return candidate
    return None


def _is_aha_article(publication: Publication) -> bool:
    return bool(publication.doi and "ahajournals.org" in (publication.url or "").lower())


def _aha_article_url(doi: str, view: str) -> str:
    return f"{STROKE_HOME}/doi/{view}/{quote(doi, safe='/')}"


def _pdf_download_candidates(publication: Publication) -> list[str]:
    candidates: list[str] = []

    def add(url: str | None) -> None:
        if url and not _is_supplement_pdf(url) and url not in candidates:
            candidates.append(url)

    add(publication.pdf_url)
    if _is_aha_article(publication):
        for view in ("epub", "epdf", "pdf", "pdfdirect"):
            add(_aha_article_url(publication.doi, view))
    elif publication.pdf_url and "/doi/pdf/" in publication.pdf_url:
        add(publication.pdf_url.replace("/doi/pdf/", "/doi/pdfdirect/", 1))
    return candidates


def _entry_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if value:
            try:
                return parsedate_to_datetime(value).astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                pass
    return None


def _recent(value: datetime | None, since: str, last_run: datetime | None) -> bool:
    if since == "all":
        return True
    if since == "last-run":
        return last_run is None or value is None or value >= last_run
    match = re.fullmatch(r"(\d+)\s*(h|d)", since.lower())
    if not match:
        raise ValueError("--since must be all, last-run, or a duration such as 24h/2d")
    delta = timedelta(hours=int(match.group(1)) * (24 if match.group(2) == "d" else 1))
    return value is None or value >= datetime.now(timezone.utc) - delta


def _dois(values: Iterable[str]) -> list[str]:
    found, seen = [], set()
    for value in values:
        match = DOI_RE.search(html.unescape(value or ""))
        if match:
            doi = normalize_doi(match.group(0))
            if doi.lower() not in seen:
                seen.add(doi.lower())
                found.append(doi)
    return found


def _clean_jats(value: str) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    for tag in soup.find_all(["title", "label"]):
        if tag.get_text(strip=True):
            tag.string = f"{tag.get_text(' ', strip=True)}: "
    return soup.get_text(" ", strip=True)


def _section_text_after_heading(soup: BeautifulSoup, heading: str) -> str:
    for node in soup.find_all(string=lambda value: value and value.strip().lower() == heading.lower()):
        parent = node.parent
        if parent and parent.name in {"h1", "h2", "h3", "h4"} and parent.parent:
            return parent.parent.get_text(" ", strip=True)
    return ""


def _safe_filename_part(value: str, max_length: int = 80) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value or "", flags=re.ASCII).strip("._-")
    cleaned = re.sub(r"_+", "_", cleaned)
    return (cleaned[:max_length].strip("._-") or "unknown")


def journal_slug(journal: str) -> str:
    value = (journal or "").lower()
    if "jama neurology" in value:
        return "JAMA-Neurology"
    if "new england journal" in value or value == "nejm":
        return "NEJM"
    if "lancet neurology" in value:
        return "Lancet-Neurology"
    if value == "the lancet" or value == "lancet":
        return "Lancet"
    if "nature reviews neurology" in value:
        return "Nature-Reviews-Neurology"
    if "annals of neurology" in value:
        return "Annals-of-Neurology"
    if value == "stroke":
        return "Stroke"
    if "neurology: clinical practice" in value or "neurology clinical practice" in value:
        return "Neurology_Clinical_Practice"
    if "neurology" in value:
        return "Neurology"
    return _safe_filename_part(journal, 48)


def pdf_filename(publication: Publication) -> str:
    pmid = _safe_filename_part(publication.pmid or "no-pmid", 24)
    journal = journal_slug(publication.journal)
    topic = _safe_filename_part(publication.title, 96)
    return f"{pmid}_{journal}_{topic}.pdf"


def discover_articles(client: HttpClient, since: str, last_run: datetime | None, limit: int) -> list[Publication]:
    publications: list[Publication] = []
    try:
        parsed = feedparser.parse(client.get_text(RSS_URL))
        for entry in parsed.entries:
            published_at = _entry_date(entry)
            if not _recent(published_at, since, last_run):
                continue
            dois = _dois([entry.get("link", ""), entry.get("id", "")])
            if not dois:
                continue
            publications.append(Publication(
                title=BeautifulSoup(entry.get("title", ""), "html.parser").get_text(" ", strip=True),
                url=urljoin(ALL_ARTICLES_URL, entry.get("link", "")), doi=dois[0],
                published=published_at.date().isoformat() if published_at else None,
                abstract=BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True),
            ))
    except Exception:
        publications = []
    if not publications:
        soup = BeautifulSoup(client.get_text(ALL_ARTICLES_URL), "html.parser")
        for link in soup.select("a[href]"):
            dois = _dois([link.get("href", "")])
            if not dois:
                continue
            publications.append(Publication(
                title=link.get_text(" ", strip=True) or dois[0],
                url=urljoin(ALL_ARTICLES_URL, link.get("href", "")), doi=dois[0],
            ))
    unique = {}
    for publication in publications:
        unique.setdefault(publication.doi.lower(), publication)
    return list(unique.values())[:limit]


def discover_jama_articles(client: HttpClient, since: str, last_run: datetime | None, limit: int) -> list[Publication]:
    publications: list[Publication] = []
    for feed_url in JAMA_NEUROLOGY_FEEDS:
        parsed = feedparser.parse(client.get_text(feed_url))
        for entry in parsed.entries:
            published_at = _entry_date(entry)
            if not _recent(published_at, since, last_run):
                continue
            doi = entry.get("prism_doi") or (_dois([entry.get("link", ""), entry.get("id", ""), str(entry)]) or [None])[0]
            if not doi:
                continue
            publications.append(Publication(
                title=BeautifulSoup(entry.get("title", ""), "html.parser").get_text(" ", strip=True),
                url=urljoin(JAMA_NEUROLOGY_HOME, entry.get("link", "")),
                doi=normalize_doi(doi),
                journal="JAMA Neurology",
                published=published_at.date().isoformat() if published_at else None,
                abstract=BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True),
            ))
    unique = {}
    for publication in publications:
        unique.setdefault(publication.doi.lower(), publication)
    return list(unique.values())[:limit]


def discover_nejm_articles(client: HttpClient, since: str, last_run: datetime | None, limit: int) -> list[Publication]:
    parsed = feedparser.parse(client.get_text(NEJM_NEUROLOGY_FEED))
    publications: list[Publication] = []
    for entry in parsed.entries:
        published_at = _entry_date(entry)
        if not _recent(published_at, since, last_run):
            continue
        doi = (_dois([entry.get("link", ""), entry.get("id", ""), str(entry)]) or [None])[0]
        if not doi:
            continue
        publications.append(Publication(
            title=BeautifulSoup(entry.get("title", ""), "html.parser").get_text(" ", strip=True),
            url=urljoin(NEJM_HOME, entry.get("link", "")),
            doi=normalize_doi(doi),
            journal="New England Journal of Medicine",
            published=published_at.date().isoformat() if published_at else entry.get("published"),
            abstract=BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True),
        ))
    unique = {}
    for publication in publications:
        unique.setdefault(publication.doi.lower(), publication)
    return list(unique.values())[:limit]


def discover_feed_articles(
    client: HttpClient,
    feed_url: str,
    journal: str,
    since: str,
    last_run: datetime | None,
    limit: int,
    base_url: str = "",
) -> list[Publication]:
    parsed = feedparser.parse(client.get_text(feed_url))
    publications: list[Publication] = []
    for entry in parsed.entries:
        published_at = _entry_date(entry)
        if not _recent(published_at, since, last_run):
            continue
        doi = entry.get("prism_doi") or (_dois([entry.get("link", ""), entry.get("id", ""), str(entry)]) or [None])[0]
        if not doi:
            continue
        publications.append(Publication(
            title=BeautifulSoup(entry.get("title", ""), "html.parser").get_text(" ", strip=True),
            url=urljoin(base_url, entry.get("link", "")),
            doi=normalize_doi(doi),
            journal=journal,
            published=published_at.date().isoformat() if published_at else entry.get("published"),
            abstract=BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True),
        ))
    unique = {}
    for publication in publications:
        unique.setdefault(publication.doi.lower(), publication)
    return list(unique.values())[:limit]


def discover_lancet_neurology_articles(client: HttpClient, since: str, last_run: datetime | None, limit: int) -> list[Publication]:
    return discover_feed_articles(client, LANCET_NEUROLOGY_FEED, "The Lancet Neurology", since, last_run, limit, LANCET_NEUROLOGY_HOME)


def discover_lancet_articles(client: HttpClient, since: str, last_run: datetime | None, limit: int) -> list[Publication]:
    return discover_feed_articles(client, LANCET_FEED, "The Lancet", since, last_run, limit, LANCET_HOME)


def discover_stroke_articles(client: HttpClient, since: str, last_run: datetime | None, limit: int) -> list[Publication]:
    return discover_feed_articles(client, STROKE_FEED, "Stroke", since, last_run, limit, STROKE_HOME)


def discover_nature_reviews_neurology_articles(client: HttpClient, since: str, last_run: datetime | None, limit: int) -> list[Publication]:
    return discover_feed_articles(client, NATURE_REVIEWS_NEUROLOGY_FEED, "Nature Reviews Neurology", since, last_run, limit)


def discover_annals_neurology_articles(client: HttpClient, since: str, last_run: datetime | None, limit: int) -> list[Publication]:
    return discover_feed_articles(client, ANNALS_NEUROLOGY_FEED, "Annals of Neurology", since, last_run, limit)


def enrich_article(client: HttpClient, publication: Publication) -> Publication:
    if not publication.doi:
        return publication
    url = f"https://doi.org/{quote(publication.doi, safe='/')}"
    try:
        soup = BeautifulSoup(client.get_text(url), "html.parser")
        title = soup.select_one("h1.article-header__title, h1.citation__title, h1")
        abstract = soup.select_one("div.abstractSection, .abstract, section.abstract")
        date = soup.select_one("meta[name='citation_publication_date'], meta[name='citation_online_date']")
        journal = soup.select_one("meta[name='citation_journal_title']")
        pdf = soup.select_one(
            "meta[name='citation_pdf_url'], link[type='application/pdf'], "
            "a[href*='/pdf/'], a[href$='.pdf']"
        )
        if title and title.get_text(strip=True):
            publication.title = title.get_text(" ", strip=True)
        if abstract and abstract.get_text(strip=True):
            publication.abstract = abstract.get_text(" ", strip=True)
        if date and date.get("content"):
            publication.published = date["content"]
        if journal and journal.get("content"):
            publication.journal = journal["content"]
        if pdf:
            pdf_href = pdf.get("content") or pdf.get("href")
            if pdf_href:
                publication.pdf_url = urljoin(url, pdf_href)
        publication.url = url
    except Exception:
        pass
    return publication


def enrich_jama_article(client: HttpClient, publication: Publication) -> Publication:
    if not publication.doi:
        return publication
    try:
        data = client.get_json(f"https://api.crossref.org/works/{quote(publication.doi, safe='')}").get("message", {})
        titles = data.get("title") or []
        if titles:
            publication.title = _clean_jats(titles[0])
        if data.get("abstract"):
            publication.abstract = _clean_jats(data["abstract"])
        if data.get("container-title"):
            publication.journal = data["container-title"][0]
        if data.get("published-print", {}).get("date-parts"):
            publication.published = "-".join(f"{part:02d}" for part in data["published-print"]["date-parts"][0])
        elif data.get("published-online", {}).get("date-parts"):
            publication.published = "-".join(f"{part:02d}" for part in data["published-online"]["date-parts"][0])
        resource = data.get("resource", {}).get("primary", {}).get("URL")
        if resource:
            publication.url = resource
        for link in data.get("link", []):
            url = link.get("URL", "")
            if "articlepdf" in url.lower() or url.lower().endswith(".pdf"):
                publication.pdf_url = url
                break
    except Exception:
        pass
    return publication


def enrich_nejm_article(client: HttpClient, publication: Publication) -> Publication:
    if not publication.doi:
        return publication
    try:
        data = client.get_json(f"https://api.crossref.org/works/{quote(publication.doi, safe='')}").get("message", {})
        titles = data.get("title") or []
        if titles:
            publication.title = _clean_jats(titles[0])
        if data.get("container-title"):
            publication.journal = data["container-title"][0]
        resource = data.get("resource", {}).get("primary", {}).get("URL")
        if resource:
            publication.url = resource.replace("http://", "https://", 1)
        for link in data.get("link", []):
            url = link.get("URL", "")
            if "/doi/pdf/" in url.lower() or url.lower().endswith(".pdf"):
                publication.pdf_url = url.replace("http://", "https://", 1)
                break
    except Exception:
        pass
    try:
        article_url = publication.url
        if "/doi/" in article_url and "/doi/full/" not in article_url:
            article_url = article_url.replace("/doi/", "/doi/full/", 1)
        soup = BeautifulSoup(client.get_text(article_url), "html.parser")
        title = soup.select_one("h1")
        if title and title.get_text(strip=True):
            publication.title = title.get_text(" ", strip=True)
        journal = soup.select_one("meta[name='citation_journal_title']")
        if journal and journal.get("content"):
            publication.journal = journal["content"]
        pdf = soup.select_one("a[href*='/doi/pdf/'], meta[name='citation_pdf_url'], link[type='application/pdf']")
        if pdf:
            pdf_href = pdf.get("content") or pdf.get("href")
            if pdf_href:
                publication.pdf_url = urljoin(article_url, pdf_href)
        abstract = _section_text_after_heading(soup, "Abstract")
        if abstract:
            publication.abstract = re.sub(r"^Abstract\s+", "", abstract).strip()
        publication.url = article_url
    except Exception:
        pass
    return publication


def enrich_publisher_article(client: HttpClient, publication: Publication) -> Publication:
    if not publication.doi:
        return publication
    try:
        soup = BeautifulSoup(client.get_text(publication.url), "html.parser")
        title = soup.select_one("meta[name='citation_title'], h1")
        journal = soup.select_one("meta[name='citation_journal_title']")
        date = soup.select_one("meta[name='citation_publication_date'], meta[name='citation_online_date']")
        description = soup.select_one("meta[name='description']")
        abstract = soup.select_one("section.abstract, div.abstract, #abstract")
        pdf_url = _main_pdf_url(soup, publication.url)
        if title:
            publication.title = title.get("content") or title.get_text(" ", strip=True)
        if journal and journal.get("content"):
            publication.journal = journal["content"]
        if date and date.get("content"):
            publication.published = date["content"]
        if abstract and abstract.get_text(strip=True):
            publication.abstract = abstract.get_text(" ", strip=True)
        elif description and description.get("content"):
            publication.abstract = description["content"]
        if pdf_url:
            publication.pdf_url = pdf_url
    except Exception:
        pass
    if not publication.pdf_url and _is_aha_article(publication):
        # AHA article pages may expose the supplemental PDF as the only literal
        # .pdf link. Derive the main PDF from the DOI; download_pdf will still
        # verify that the response contains real PDF bytes.
        publication.pdf_url = _aha_article_url(publication.doi, "pdf")
    try:
        data = client.get_json(f"https://api.crossref.org/works/{quote(publication.doi, safe='')}").get("message", {})
        if data.get("abstract"):
            publication.abstract = _clean_jats(data["abstract"])
        if data.get("container-title"):
            publication.journal = data["container-title"][0]
        if not publication.pdf_url:
            for link in data.get("link", []):
                url = link.get("URL", "")
                is_pdf = "pdf" in url.lower() or url.lower().endswith(".pdf")
                if is_pdf and not _is_supplement_pdf(url):
                    publication.pdf_url = url
                    break
    except Exception:
        pass
    return publication


def download_pdf(client: HttpClient, publication: Publication, output_dir: Path) -> Publication:
    """Save a real PDF as PMID_Journal_Topic.pdf; never save an HTML login/error page."""
    if not publication.pdf_url or not publication.pmid or _is_supplement_pdf(publication.pdf_url):
        return publication
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / pdf_filename(publication)
    legacy_path = output_dir / f"{publication.pmid}.pdf"
    candidates = _pdf_download_candidates(publication)
    try:
        if not path.exists() and legacy_path.exists():
            publication.local_pdf = str(legacy_path)
            return publication
        if not path.exists():
            content = b""
            for pdf_url in candidates:
                try:
                    content = client.get_bytes(
                        pdf_url,
                        headers={
                            "Accept": "application/pdf,*/*;q=0.8",
                            "Referer": publication.url or publication.pdf_url,
                        },
                    )
                except Exception:
                    continue
                if content.startswith(b"%PDF"):
                    publication.pdf_url = pdf_url
                    break
            else:
                return publication
            path.write_bytes(content)
        publication.local_pdf = str(path)
    except Exception:
        pass
    return publication


def discover_podcasts(client: HttpClient, since: str, last_run: datetime | None, limit: int) -> list[Publication]:
    soup = BeautifulSoup(client.get_text(PODCAST_URL), "html.parser")
    results = []
    for link in soup.select("a[href]"):
        href, title = link.get("href", ""), link.get_text(" ", strip=True)
        normalized = urljoin(PODCAST_URL, href)
        # Neurology's page also links to topic pages and external podcast apps;
        # only /media/podcast/ links represent individual episodes.
        if title and "/media/podcast/" in normalized.lower():
            results.append(Publication(title=title, url=normalized, journal="Neurology Podcast", is_podcast=True))
    return list({item.url: item for item in results}.values())[:limit]


def discover_jama_podcasts(client: HttpClient, since: str, last_run: datetime | None, limit: int) -> list[Publication]:
    parsed = feedparser.parse(client.get_text(JAMA_NEUROLOGY_PODCAST_FEED))
    results = []
    for entry in parsed.entries:
        published_at = _entry_date(entry)
        if not _recent(published_at, since, last_run):
            continue
        audio_url = None
        for link in entry.get("links", []):
            if link.get("type", "").startswith("audio/") or link.get("href", "").lower().endswith((".mp3", ".m4a")):
                audio_url = link.get("href")
                break
        results.append(Publication(
            title=BeautifulSoup(entry.get("title", ""), "html.parser").get_text(" ", strip=True),
            url=entry.get("link", ""),
            doi=(_dois([entry.get("link", ""), entry.get("id", ""), str(entry)]) or [None])[0],
            journal="JAMA Neurology Author Interviews",
            published=published_at.date().isoformat() if published_at else None,
            abstract=BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True),
            audio_url=audio_url,
            is_podcast=True,
        ))
    return results[:limit]


def enrich_podcast(client: HttpClient, publication: Publication) -> Publication:
    try:
        soup = BeautifulSoup(client.get_text(publication.url), "html.parser")
        description = soup.select_one("meta[name='description'], .article__body, .podcast-description, .abstract")
        date = soup.select_one("meta[property='article:published_time'], time, meta[name='citation_publication_date']")
        audio = soup.select_one("audio source[src], audio[src], a[href$='.mp3'], a[href$='.m4a']")
        if description and description.get("content"):
            publication.abstract = description["content"]
        elif description:
            publication.abstract = description.get_text(" ", strip=True)
        if date:
            publication.published = date.get("content") or date.get("datetime") or date.get_text(" ", strip=True)
        if audio:
            publication.audio_url = urljoin(publication.url, audio.get("src") or audio.get("href"))
    except Exception:
        pass
    return publication
