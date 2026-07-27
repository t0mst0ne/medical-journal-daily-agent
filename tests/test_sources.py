import tempfile
import unittest
from pathlib import Path

from neurology_agent.models import Publication
from neurology_agent.sources import download_pdf, enrich_publisher_article


class PublisherClient:
    def __init__(self, html: str):
        self.html = html

    def get_text(self, url: str) -> str:
        return self.html

    def get_json(self, url: str) -> dict:
        return {"message": {}}


class DownloadClient:
    def __init__(self):
        self.calls = []

    def get_bytes(self, url: str, headers=None) -> bytes:
        self.calls.append(url)
        return b"%PDF-1.7\n"


class CandidateDownloadClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get_bytes(self, url: str, headers=None) -> bytes:
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class PublisherPdfSelectionTests(unittest.TestCase):
    def test_prefers_citation_pdf_over_earlier_supplement_link(self):
        client = PublisherClient(
            """
            <a href="/doi/suppl/10.1161/example/suppl_file/example-s01.pdf">Supplement</a>
            <meta name="citation_pdf_url" content="/doi/pdf/10.1161/example?download=true">
            """
        )
        publication = Publication(
            title="Example",
            url="https://www.ahajournals.org/doi/abs/10.1161/example",
            doi="10.1161/example",
        )

        enrich_publisher_article(client, publication)

        self.assertEqual(
            publication.pdf_url,
            "https://www.ahajournals.org/doi/pdf/10.1161/example?download=true",
        )

    def test_prefers_main_epub_over_earlier_supplement_link(self):
        client = PublisherClient(
            """
            <a href="/doi/suppl/10.1161/example/suppl_file/example-s01.pdf">Supplement</a>
            <a href="/doi/epub/10.1161/example">PDF/EPUB</a>
            """
        )
        publication = Publication(
            title="Example",
            url="https://www.ahajournals.org/doi/abs/10.1161/example",
            doi="10.1161/example",
        )

        enrich_publisher_article(client, publication)

        self.assertEqual(
            publication.pdf_url,
            "https://www.ahajournals.org/doi/epub/10.1161/example",
        )

    def test_uses_aha_pdf_fallback_when_page_only_has_supplement(self):
        client = PublisherClient(
            '<a href="/doi/suppl/10.1161/example/suppl_file/example-s01.pdf">Supplement</a>'
        )
        publication = Publication(
            title="Example",
            url="https://www.ahajournals.org/doi/abs/10.1161/example",
            doi="10.1161/example",
        )

        enrich_publisher_article(client, publication)

        self.assertEqual(
            publication.pdf_url,
            "https://www.ahajournals.org/doi/pdf/10.1161/example",
        )

    def test_download_rejects_supplement_url(self):
        publication = Publication(
            title="Example",
            url="https://www.ahajournals.org/doi/abs/10.1161/example",
            doi="10.1161/example",
            pmid="12345678",
            pdf_url=(
                "https://www.ahajournals.org/doi/suppl/10.1161/example/"
                "suppl_file/example-s01.pdf"
            ),
        )

        client = DownloadClient()
        with tempfile.TemporaryDirectory() as directory:
            download_pdf(client, publication, Path(directory))
            self.assertEqual(client.calls, [])
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertIsNone(publication.local_pdf)

    def test_download_tries_aha_main_article_formats_until_real_pdf(self):
        epub = "https://www.ahajournals.org/doi/epub/10.1161/example"
        epdf = "https://www.ahajournals.org/doi/epdf/10.1161/example"
        pdf = "https://www.ahajournals.org/doi/pdf/10.1161/example"
        client = CandidateDownloadClient({
            epub: b"<html>reader</html>",
            epdf: RuntimeError("403"),
            pdf: b"%PDF-1.7\nmain article",
        })
        publication = Publication(
            title="Example",
            url="https://www.ahajournals.org/doi/abs/10.1161/example",
            doi="10.1161/example",
            pmid="12345678",
            pdf_url=epub,
        )

        with tempfile.TemporaryDirectory() as directory:
            download_pdf(client, publication, Path(directory))

            self.assertEqual(client.calls, [epub, epdf, pdf])
            self.assertEqual(publication.pdf_url, pdf)
            self.assertIsNotNone(publication.local_pdf)
            self.assertTrue(Path(publication.local_pdf).read_bytes().startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
