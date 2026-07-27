import re
from urllib.parse import quote

from .http import HttpClient, env_email
from .models import Publication


def _digits(value) -> str | None:
    match = re.fullmatch(r"\s*(\d{5,9})\s*", str(value or ""))
    return match.group(1) if match else None


def crossref_pmid(client: HttpClient, doi: str) -> str | None:
    try:
        data = client.get_json(f"https://api.crossref.org/works/{quote(doi, safe='')}")
        message = data.get("message", {})
        for assertion in message.get("assertion", []):
            label = f"{assertion.get('name', '')} {assertion.get('label', '')}".lower()
            if "pmid" in label or "pubmed" in label:
                value = _digits(assertion.get("value"))
                if value:
                    return value
    except Exception:
        return None
    return None


def pubmed_pmid(client: HttpClient, doi: str) -> str | None:
    params = f"db=pubmed&term={quote(doi + '[doi]')}&retmode=json&tool=neurology-agent"
    if env_email():
        params += f"&email={quote(env_email())}"
    try:
        data = client.get_json(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{params}")
        ids = data.get("esearchresult", {}).get("idlist", [])
        return ids[0] if ids else None
    except Exception:
        return None


def resolve_pmid(client: HttpClient, publication: Publication) -> Publication:
    if not publication.doi:
        return publication
    pmid = crossref_pmid(client, publication.doi)
    if pmid:
        publication.pmid, publication.pmid_source = pmid, "crossref"
        return publication
    pmid = pubmed_pmid(client, publication.doi)
    if pmid:
        publication.pmid, publication.pmid_source = pmid, "pubmed"
    return publication
