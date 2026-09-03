#!/usr/bin/env python3
"""Hakee Ilveksen peliryhmien ottelut HJK Cupin taso-sivustolta.

Kirjoittaa tulokset tiedostoon docs/data/games.json. Jos yksittaisen sarjan
haku epaonnistuu, sarjan aiemmin haettu data pidetaan ennallaan eika koko ajo
kaadu.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TOURNAMENT = "hjk_0031"
BASE_URL = "https://hjkcup.fi/taso/joukkue.php"
CLUB_MATCH = "ilves"          # oma joukkue tunnistetaan nimesta
TZ = ZoneInfo("Europe/Helsinki")

REQUEST_DELAY = 2.0           # sekuntia pyyntojen valissa
REQUEST_TIMEOUT = 30
MAX_ATTEMPTS = 4              # sisaltaa evastekierroksen ja verkkovirheiden uusinnat
RETRY_DELAY = 2.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# sarja-avain -> joukkue-id taso-jarjestelmassa
TEAMS: list[tuple[str, str]] = [
    ("U9", "35224617"),
    ("U10", "35224897"),
    ("U11", "35222219"),
    ("U12", "35224865"),
    ("TU11", "35222065"),
    ("TU12", "35224889"),
    ("TU13", "35224802"),
]

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "docs" / "data" / "games.json"

TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{2})$")
DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})?\.?$")
RESULT_RE = re.compile(r"\d+\s*[-–]\s*\d+")
# taso palauttaa ensimmaiselle pyynnolle JS-tyngan joka ohjaa samaan osoitteeseen
# ja asettaa samalla TASO_-session evasteen
REDIRECT_STUB_RE = re.compile(r"window\.location\.replace")
REDIRECT_TARGET_RE = re.compile(r"""=\s*['"]([A-Za-z0-9+/=]{16,})['"]""")


def team_url(series: str, team_id: str) -> str:
    return f"{BASE_URL}?joukkue={team_id}&turnaus={TOURNAMENT}&sarja={series}"


def fetch_html(session: requests.Session, url: str) -> str:
    """Hakee sivun ja selvittaa taso-jarjestelman JS-uudelleenohjauksen.

    Ensimmainen pyynto uudelle sessiolle palauttaa vain script-tyngan
    (window.location.replace(atob(a))) ja asettaa TASO_-evasteen. Sama osoite
    haetaan silloin uudelleen, jolloin palvelin palauttaa varsinaisen sivun.
    Verkkovirheita yritetaan uudelleen, koska palvelin katkoo ajoittain
    keep-alive-yhteyksia.
    """
    html = ""
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            time.sleep(RETRY_DELAY * attempt)
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as error:
            last_error = error
            session.close()  # pakota uusi yhteys katkenneen tilalle
            continue
        response.encoding = response.encoding or "utf-8"
        html = response.text

        if not is_redirect_stub(html):
            return html

        target = REDIRECT_TARGET_RE.search(html)
        if target:
            try:
                decoded = base64.b64decode(target.group(1)).decode("utf-8", "replace")
                if "joukkue.php" in decoded or "sarja.php" in decoded:
                    url = requests.compat.urljoin(response.url, decoded)
            except (ValueError, base64.binascii.Error):
                pass
        last_error = RuntimeError("palvelin palautti vain uudelleenohjaustyngan")

    if not html or is_redirect_stub(html):
        raise last_error or RuntimeError("sivun haku ei onnistunut")
    return html


def is_redirect_stub(html: str) -> bool:
    return len(html) < 2000 and bool(REDIRECT_STUB_RE.search(html))


def clean_text(node: Any) -> str:
    """Solun teksti siistittyna. <wbr> poistetaan ettei nimiin tule valilyontia."""
    if node is None:
        return ""
    if hasattr(node, "get_text"):
        for wbr in node.find_all("wbr"):
            wbr.extract()
        text = node.get_text("")
    else:
        text = str(node)
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def parse_date(raw: str, today: dt.date) -> str | None:
    """'5.9.' -> '2026-09-05'. Vuosi paatellaan turnauksen ajankohdasta."""
    match = DATE_RE.match(raw.strip())
    if not match:
        return None
    day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
    if year:
        return f"{int(year):04d}-{month:02d}-{day:02d}"
    for candidate in (today.year, today.year + 1, today.year - 1):
        try:
            date = dt.date(candidate, month, day)
        except ValueError:
            continue
        # turnauspaivat ovat lahitulevaisuudessa tai juuri menneet
        if -120 <= (date - today).days <= 245:
            return date.isoformat()
    return None


def split_time_and_result(raw: str) -> tuple[str, str]:
    """ml_tulosklo-solu sisaltaa joko kellonajan tai pelatun ottelun tuloksen."""
    value = raw.strip()
    if not value:
        return "", ""
    time_match = TIME_RE.match(value)
    if time_match:
        return f"{int(time_match.group(1)):02d}:{time_match.group(2)}", ""
    if RESULT_RE.search(value):
        return "", re.sub(r"\s*[-–]\s*", " - ", value).strip()
    return "", ""


def parse_games(html: str, series: str, today: dt.date) -> list[dict[str, Any]]:
    """Poimii sivulta oman joukkueen ottelut.

    Sivulla on useita matchlist-listoja: oma otteluohjelma seka ehdolliset
    jatko-ottelut ("jos alkulohkon ensimmainen"), joissa joukkueet ovat vain
    paikanvaraajia. Otetaan mukaan vain ottelut joissa Ilves on mukana.
    """
    soup = BeautifulSoup(html, "html.parser")
    games: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in soup.select("ul.matchlist li.match"):
        def cell(name: str) -> str:
            return clean_text(item.select_one(f"div.{name}"))

        home = cell("ml_kotisiisti")
        away = cell("ml_vierassiisti")
        if not home or not away:
            continue
        is_home = CLUB_MATCH in home.lower()
        is_away = CLUB_MATCH in away.lower()
        if not (is_home or is_away):
            continue

        number = cell("ml_ottelunro")
        link = item.find_parent("a")
        href = link.get("href", "") if link else ""
        match_id = ""
        if href:
            id_match = re.search(r"ottelu=(\d+)", href)
            if id_match:
                match_id = id_match.group(1)
        key = match_id or f"{series}-{number}-{home}-{away}"
        if key in seen:
            continue
        seen.add(key)

        raw_date = cell("ml_pvm")
        kickoff, result = split_time_and_result(cell("ml_tulosklo"))
        games.append(
            {
                "id": key,
                "match_id": match_id,
                "match_number": number,
                "series": series,
                "date": raw_date,
                "date_iso": parse_date(raw_date, today),
                "time": kickoff,
                "venue": cell("ml_kenttanimi"),
                "home": home,
                "away": away,
                "opponent": away if is_home else home,
                "is_home": is_home,
                "result": result,
                "played": bool(result),
                "url": requests.compat.urljoin("https://hjkcup.fi/taso/", href) if href else "",
            }
        )

    games.sort(key=lambda g: (g["date_iso"] or "9999-99-99", g["time"] or "99:99", g["match_number"]))
    return games


def load_previous(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def carry_over_times(games: list[dict[str, Any]], previous: list[dict[str, Any]]) -> None:
    """Pelatun ottelun kohdalla sivusto nayttaa tuloksen kellonajan tilalla."""
    old_times = {g.get("id"): g.get("time") for g in previous if g.get("time")}
    for game in games:
        if not game["time"] and old_times.get(game["id"]):
            game["time"] = old_times[game["id"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY)
    args = parser.parse_args()

    now = dt.datetime.now(TZ)
    today = now.date()
    previous = load_previous(args.output)
    previous_series: dict[str, Any] = previous.get("series", {}) if previous else {}

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8",
        }
    )

    series_data: dict[str, Any] = {}
    failures: list[str] = []

    for index, (series, team_id) in enumerate(TEAMS):
        if index:
            time.sleep(args.delay)
        url = team_url(series, team_id)
        old = previous_series.get(series, {})
        old_games = old.get("games", []) if isinstance(old, dict) else []
        try:
            html = fetch_html(session, url)
            games = parse_games(html, series, today)
            if not games:
                raise ValueError("otteluita ei loytynyt sivulta")
            carry_over_times(games, old_games)
        except Exception as error:  # yksi sarja ei kaada koko ajoa
            failures.append(series)
            print(f"[VIRHE] {series}: {error}", file=sys.stderr)
            series_data[series] = {
                "team_id": team_id,
                "url": url,
                "ok": False,
                "error": f"{type(error).__name__}: {error}",
                "fetched_at": old.get("fetched_at") if isinstance(old, dict) else None,
                "stale": True,
                "games": old_games,
            }
            continue

        print(f"[OK] {series}: {len(games)} ottelua")
        series_data[series] = {
            "team_id": team_id,
            "url": url,
            "ok": True,
            "error": None,
            "fetched_at": now.isoformat(timespec="seconds"),
            "stale": False,
            "games": games,
        }

    all_games = [game for series, _ in TEAMS for game in series_data[series]["games"]]
    all_games.sort(key=lambda g: (g["date_iso"] or "9999-99-99", g["time"] or "99:99", g["series"]))

    payload = {
        "updated_at": now.isoformat(timespec="seconds"),
        "tournament": TOURNAMENT,
        "club": "Ilves",
        "series_order": [series for series, _ in TEAMS],
        "series": series_data,
        "games": all_games,
        "failed_series": failures,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1, sort_keys=False)
        handle.write("\n")

    print(f"Kirjoitettu {args.output} ({len(all_games)} ottelua, {len(failures)} virhetta)")
    # onnistuneita sarjoja on aina jotain -> paluukoodi 0, jotta workflow committaa datan
    return 0 if len(failures) < len(TEAMS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
