"""Real-site scrapers (Selenium + headless Chromium), adapted from PA-Taller1/scripts/main.py.

One function per source. Each opens its own browser (one per Dask task), returns
raw dicts, and raises ScrapeError when the page didn't yield results — so the
Prefect task retries it (docs/design.md §6.1). Parsing/validation lives in clean.py.

Sources chosen by a live spike on 2026-10-09 (evidence/stage-04/AC-04.0_*):
  flights → Google Flights · hotels → Booking.com · cars → Booking.com Cars.
"""
from __future__ import annotations

import contextlib
import os
import time
from datetime import date

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
PAGE_TIMEOUT = int(os.environ.get("SCRAPE_PAGE_TIMEOUT", "30"))


class ScrapeError(Exception):
    """Page loaded but produced no results (blocked, layout change, empty)."""


@contextlib.contextmanager
def browser():
    options = Options()
    for arg in (
        "--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
        "--window-size=1920,1080", "--lang=es-CO", f"--user-agent={USER_AGENT}",
        "--disable-blink-features=AutomationControlled",
    ):
        options.add_argument(arg)
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.binary_location = "/usr/bin/chromium"
    driver = webdriver.Chrome(service=Service("/usr/bin/chromedriver"), options=options)
    driver.set_page_load_timeout(PAGE_TIMEOUT)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    try:
        yield driver
    finally:
        driver.quit()


def _wait_for(driver, css: str, what: str) -> None:
    try:
        WebDriverWait(driver, PAGE_TIMEOUT).until(EC.presence_of_element_located((By.CSS_SELECTOR, css)))
    except TimeoutException as exc:
        raise ScrapeError(f"{what}: results never appeared ({driver.title!r})") from exc


def _scroll(driver, steps: int = 4, pause: float = 1.0) -> None:
    """Trigger lazy loading (PA-Taller1 _scroll_para_cargar)."""
    for _ in range(steps):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause)


# ───────────────────────── Google Flights ─────────────────────────
# Each result row carries a full-sentence aria-label ("A partir de 177805 pesos
# colombianos. Vuelo directo de Wingo. Sale de ... a las 17:20. Llega ... a las
# 18:53. Duración total: 1 h 33 min."), far more stable than its hashed classes.

def scrape_google_flights(origin: str, destination: str, day: date) -> list[dict]:
    url = (
        "https://www.google.com/travel/flights?hl=es&curr=COP&q="
        f"Flights%20to%20{destination}%20from%20{origin}%20on%20{day.isoformat()}%20oneway"
    )
    with browser() as driver:
        driver.get(url)
        _wait_for(driver, "[aria-label^='A partir de']", "google_flights")
        labels = {
            el.get_attribute("aria-label")
            for el in driver.find_elements(By.CSS_SELECTOR, "[aria-label^='A partir de']")
        }
    if not labels:
        raise ScrapeError("google_flights: no flight rows")
    return [
        {"source": "google_flights", "origin": origin, "destination": destination,
         "day": day.isoformat(), "label": label}
        for label in labels if label
    ]


# ───────────────────────── Booking.com hotels ─────────────────────────

def scrape_booking_hotels(city_name: str, city_code: str, check_in: date, check_out: date) -> list[dict]:
    url = (
        "https://www.booking.com/searchresults.es.html?"
        f"ss={city_name}&checkin={check_in.isoformat()}&checkout={check_out.isoformat()}"
        "&group_adults=1&no_rooms=1&selected_currency=COP"
    )
    with browser() as driver:
        driver.get(url)
        _wait_for(driver, "[data-testid='property-card']", "booking_hotels")
        _scroll(driver, steps=2)
        rows = driver.execute_script("""
            return [...document.querySelectorAll("[data-testid='property-card']")].map(card => ({
                name:   card.querySelector("[data-testid='title']")?.innerText,
                price:  card.querySelector("[data-testid='price-and-discounted-price']")?.innerText,
                rating: card.querySelector("[data-testid='review-score']")?.innerText,
                url:    card.querySelector("a[data-testid='title-link']")?.href,
            }));
        """)
    if not rows:
        raise ScrapeError("booking_hotels: no property cards")
    return [
        {"source": "booking", "city": city_code, "check_in": check_in.isoformat(),
         "check_out": check_out.isoformat(), **row}
        for row in rows
    ]


# ───────────────────────── Booking.com Cars ─────────────────────────
# Car cards have no test ids; every card shows a supplier logo
# (img alt="Supplied by X"), so we anchor on it and climb to the card.

def scrape_booking_cars(city_code: str, pickup: date, dropoff: date) -> list[dict]:
    url = (
        "https://cars.booking.com/search-results?"
        f"locationIata={city_code}&dropLocationIata={city_code}"
        f"&puDay={pickup.day}&puMonth={pickup.month}&puYear={pickup.year}&puHour=10&puMinute=0"
        f"&doDay={dropoff.day}&doMonth={dropoff.month}&doYear={dropoff.year}&doHour=10&doMinute=0"
        "&driversAge=30&currency=COP"
    )
    with browser() as driver:
        driver.get(url)
        _wait_for(driver, "img[alt^='Supplied by']", "booking_cars")
        _scroll(driver, steps=2)
        rows = driver.execute_script("""
            const cards = new Set();
            for (const img of document.querySelectorAll("img[alt^='Supplied by']")) {
                let el = img;
                while (el && !(el.innerText || "").includes("Price for")) el = el.parentElement;
                if (el) cards.add(el);
            }
            return [...cards].map(card => ({
                vendor: card.querySelector("img[alt^='Supplied by']").alt.replace("Supplied by ", ""),
                text: card.innerText,
            }));
        """)
    if not rows:
        raise ScrapeError("booking_cars: no car cards")
    return [
        {"source": "booking_cars", "city": city_code, "pickup_date": pickup.isoformat(),
         "dropoff_date": dropoff.isoformat(), **row}
        for row in rows
    ]


if __name__ == "__main__":  # manual smoke test inside the image
    import json
    import sys
    from datetime import timedelta

    d = date.today() + timedelta(days=10)
    which = sys.argv[1]
    try:
        if which == "flights":
            out = scrape_google_flights("BOG", "CTG", d)
        elif which == "hotels":
            out = scrape_booking_hotels("Cartagena", "CTG", d, d + timedelta(days=3))
        else:
            out = scrape_booking_cars("CTG", d, d + timedelta(days=3))
    except (ScrapeError, WebDriverException) as e:
        sys.exit(f"FAILED: {e}")
    print(len(out))
    print(json.dumps(out[:3], ensure_ascii=False, indent=1))
