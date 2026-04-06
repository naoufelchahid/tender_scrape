"""Playwright scraper for tender result documents on marchespublics.gov.ma."""
import asyncio
import logging
import os
import re
import unicodedata
import random
from pathlib import Path
from typing import Optional

from playwright.async_api import Page, async_playwright
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseAdvancedSearch&AllAnn"


def normalize_name(name: str) -> str:
    """Normalize a name for comparison: strip accents, lowercase, collapse whitespace."""
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    without_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(without_accents.lower().split())


async def _human_delay(min_sec: float = 1.0, max_sec: float = 3.0):
    await asyncio.sleep(random.uniform(min_sec, max_sec))


class ResultScraper:
    def __init__(self, downloads_dir: str = "download_results"):
        self.downloads_dir = Path(downloads_dir)
        self.downloads_dir.mkdir(exist_ok=True)

    async def search_and_download(
        self, page: Page, search_ref: str, buyer_name: Optional[str], tender_ref: str
    ) -> Optional[str]:
        """Search marchespublics.gov.ma for PV document and download it.

        Args:
            page: Playwright page instance.
            search_ref: Original reference to search for.
            buyer_name: Buyer name from Fuseki for tuple matching.
            tender_ref: Composite tender ref (used for filename).

        Returns:
            Local file path of downloaded PDF, or None.
        """
        logger.info(f"Searching for results: ref={search_ref}, buyer={buyer_name}")
        try:
            await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
            await _human_delay(1, 2)

            # Fill reference field
            ref_input = await page.query_selector(
                "input#ctl0_CONTENU_PAGE_AdvancedSearch_reference"
            )
            if not ref_input:
                logger.error("Reference input field not found")
                return None

            await ref_input.fill(search_ref)

            # Select "Annonce d'extrait de PV" (value=5)
            await page.wait_for_selector(
                "select#ctl0_CONTENU_PAGE_AdvancedSearch_annonceType"
            )
            await page.select_option(
                "select#ctl0_CONTENU_PAGE_AdvancedSearch_annonceType", "5"
            )

            # Submit search
            await page.click(
                "input#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche"
            )
            await page.wait_for_load_state("networkidle")
            await _human_delay(2, 3)

            # Set page size to 500
            page_size = await page.query_selector(
                "select#ctl0_CONTENU_PAGE_resultSearch_listePageSizeTop"
            )
            if page_size:
                await page.select_option(
                    "select#ctl0_CONTENU_PAGE_resultSearch_listePageSizeTop", "500"
                )
                await page.wait_for_load_state("networkidle")
                await _human_delay(2, 3)

            # Parse results and match by (ref, buyer) tuple
            return await self._find_and_download(page, search_ref, buyer_name, tender_ref)

        except Exception as e:
            logger.error(f"Scraping error for {tender_ref}: {e}")
            return None

    async def _find_and_download(
        self, page: Page, search_ref: str, buyer_name: Optional[str], tender_ref: str
    ) -> Optional[str]:
        """Paginate through results, match by buyer name, download PDF."""
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        total_pages = 1
        page_count_el = soup.find(
            "span", id="ctl0_CONTENU_PAGE_resultSearch_nombrePageTop"
        )
        if page_count_el:
            try:
                total_pages = int(page_count_el.get_text(strip=True))
            except ValueError:
                pass

        normalized_buyer = normalize_name(buyer_name) if buyer_name else None

        for current_page in range(1, total_pages + 1):
            logger.info(f"Searching page {current_page}/{total_pages}")
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            buyer_divs = soup.find_all(
                "div", id=lambda x: x and "panelBlocDenomination" in x
            )
            tender_links = await page.query_selector_all(
                'a[href*="EntrepriseDetailConsultation"]'
            )

            for idx, buyer_div in enumerate(buyer_divs):
                if idx >= len(tender_links):
                    break

                page_buyer = buyer_div.get_text(strip=True)
                page_buyer = re.sub(
                    r"^Acheteur public\s*:\s*", "", page_buyer, flags=re.IGNORECASE
                )
                page_buyer = " ".join(page_buyer.split())

                # Match by tuple: buyer name comparison
                if normalized_buyer and normalize_name(page_buyer) != normalized_buyer:
                    continue

                # If no buyer from Fuseki, skip matching (take first result)
                logger.info(f"Matched tender row by buyer: {page_buyer}")

                await tender_links[idx].click()
                await page.wait_for_load_state("networkidle")
                await _human_delay(2, 3)

                # Find download link
                download_link = await page.query_selector(
                    'a:has-text("Fichier joint"), a[href*="EntrepriseDownloadAvisJAL"]'
                )
                if download_link:
                    async with page.expect_download() as dl_info:
                        await download_link.click()
                    download = await dl_info.value

                    ext = Path(download.suggested_filename).suffix or ".pdf"
                    safe_ref = tender_ref.replace("/", "_")
                    filename = f"{safe_ref}_result{ext}"
                    filepath = self.downloads_dir / filename
                    await download.save_as(str(filepath))
                    logger.info(f"Downloaded: {filepath}")
                    return str(filepath)

                logger.warning("No download link on detail page")
                await page.go_back()
                await page.wait_for_load_state("networkidle")
                return None

            # Navigate to next page
            if current_page < total_pages:
                next_link = await page.query_selector(
                    f'a[href*="numPageEnCours={current_page + 1}"]'
                )
                if next_link:
                    await next_link.click()
                    await page.wait_for_load_state("networkidle")
                    await _human_delay(2, 3)
                else:
                    break

        logger.info(f"No results found for {tender_ref}")
        return None
