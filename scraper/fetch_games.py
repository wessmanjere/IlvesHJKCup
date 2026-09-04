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
    candidates = []
    for year_candidate in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(dt.date(year_candidate, month, day))
        except ValueError:
            continue
    if not candidates:
        return None
    # sivu ei kerro vuotta, joten valitaan ajallisesti lahin vaihtoehto
    return min(candidates, key=lambda date: abs((date - today).days)).isoformat()


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


# Ehdollisten jatko-otteluiden paikanvaraajat. Naita EI koskaan naytela
# otteluna: ottelu paasee listalle vain jos Ilves on vahvistettu osallistuja.
PLACEHOLDER_RES = (
    re.compile(r"^[A-Z]/[IVXLC]+$"),                    # A/I, B/IV, A/VIII
    re.compile(r"^(?:Voittaja|Haviaja|Häviäjä)\s+\d+$", re.I),  # Voittaja 531
    re.compile(r"^\d*\.?\s*paras\s+\w+$", re.I),      # Paras seitsemas
)
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def is_placeholder(name: str) -> bool:
    """Onko nimi paikanvaraaja oikean joukkueen sijaan.

    Tuntematon muoto tulkitaan oikeaksi joukkueeksi: vaara tulkinta siihen
    suuntaan on korjattavissa, kun taas oikean ottelun hiljainen piilottaminen
    ei nayisi mitenkaan.
    """
    value = name.strip()
    return bool(value) and any(pattern.match(value) for pattern in PLACEHOLDER_RES)


def roman_to_int(roman: str) -> int | None:
    total = 0
    previous = 0
    for char in reversed(roman.upper()):
        value = ROMAN_VALUES.get(char)
        if value is None:
            return None
        total += value if value >= previous else -value
        previous = max(previous, value)
    return total or None


def placeholder_label(name: str) -> str:
    """Paikanvaraaja luettavaan muotoon, esim. 'B/IV' -> 'Lohko B, 4.'."""
    value = name.strip()

    group = re.match(r"^([A-Z])/([IVXLC]+)$", value)
    if group:
        place = roman_to_int(group.group(2))
        if place:
            return f"Lohko {group.group(1)}, {place}."
        return f"Lohko {group.group(1)}"

    bracket = re.match(r"^(Voittaja|Haviaja|Häviäjä)\s+(\d+)$", value, re.I)
    if bracket:
        word = "voittaja" if bracket.group(1).lower().startswith("voit") else "häviäjä"
        return f"Ottelun {bracket.group(2)} {word}"

    return value


def match_identity(item: Any, series: str, number: str, home: str, away: str) -> tuple[str, str]:
    """Ottelun pysyva tunniste. Ottelu-id sailyy paikanvaraajan ratkeamisen yli."""
    link = item.find_parent("a")
    href = link.get("href", "") if link else ""
    match_id = ""
    if href:
        found = re.search(r"ottelu=(\d+)", href)
        if found:
            match_id = found.group(1)
    key = match_id or f"{series}-{number}-{home}-{away}"
    return key, match_id


def extract_games(
    scope: Any,
    series: str,
    today: dt.date,
    playoff_ids: set[str] | None = None,
    force_stage: str | None = None,
) -> list[dict[str, Any]]:
    """Poimii annetusta osasta ne ottelut joissa Ilves on vahvistettu mukana."""
    playoff_ids = playoff_ids or set()
    games: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in scope.select("ul.matchlist li.match"):
        def cell(*names: str) -> str:
            # taso-asennukset kayttavat eri luokkanimia (esim. ml_pvm /
            # ml_pvmsiisti), joten kokeillaan vaihtoehdot jarjestyksessa
            for name in names:
                node = item.select_one(f"div.{name}")
                if node is not None:
                    return clean_text(node)
            return ""

        home = cell("ml_kotisiisti", "ml_koti")
        away = cell("ml_vierassiisti", "ml_vieras")
        if not home or not away:
            continue

        # R1: Ilveksen oma nimi ratkaisee. Paikanvaraaja ei koskaan sisalla
        # "Ilves", joten spekulatiiviset rivit karsiutuvat tassa.
        is_home = CLUB_MATCH in home.lower() and not is_placeholder(home)
        is_away = CLUB_MATCH in away.lower() and not is_placeholder(away)
        if not (is_home or is_away):
            continue

        number = cell("ml_ottelunro")
        key, match_id = match_identity(item, series, number, home, away)
        if key in seen:
            continue
        seen.add(key)

        opponent = away if is_home else home
        opponent_open = is_placeholder(opponent)

        raw_date = cell("ml_pvm", "ml_pvmsiisti")
        kickoff, result = split_time_and_result(cell("ml_tulosklo"))
        # uudemmat taso-versiot merkitsevat pelatun ottelun li-luokkaan
        played = bool(result) or "played" in (item.get("class") or [])
        stage = force_stage or ("jatko" if match_id and match_id in playoff_ids else "lohko")

        games.append(
            {
                "id": key,
                "match_id": match_id,
                "match_number": number,
                "series": series,
                "stage": stage,
                "date": raw_date,
                "date_iso": parse_date(raw_date, today),
                "time": kickoff,
                "venue": cell("ml_kenttanimi", "ml_kentta"),
                "home": home,
                "away": away,
                "opponent": opponent,
                "opponent_confirmed": not opponent_open,
                "opponent_placeholder": opponent if opponent_open else "",
                "opponent_label": placeholder_label(opponent) if opponent_open else "",
                "is_home": is_home,
                "result": result,
                "played": played,
                "url": requests.compat.urljoin("https://hjkcup.fi/taso/", href_of(item)),
            }
        )

    return sort_games(games)


def href_of(item: Any) -> str:
    link = item.find_parent("a")
    return link.get("href", "") if link else ""


def sort_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    games.sort(key=lambda g: (g["date_iso"] or "9999-99-99", g["time"] or "99:99", g["match_number"]))
    return games


def parse_team_page(html: str, series: str, today: dt.date) -> dict[str, Any]:
    """Lukee joukkuesivun: oma otteluohjelma + ehdollisten jatko-otteluiden tiedot.

    Ensimmainen matchlist on joukkueen oma vahvistettu otteluohjelma. Loput ovat
    skenaariolistoja ("Jatko-ottelut, jos alkulohkon ensimmainen"), joista
    luetaan vain jatko-otteluiden ottelu-id:t, paivat ja kelloajat.
    """
    soup = BeautifulSoup(html, "html.parser")
    lists = soup.select("ul.matchlist")

    playoff_ids: set[str] = set()
    playoff_dates: set[str] = set()
    playoff_times: list[str] = []

    for scenario in lists[1:]:
        for item in scenario.select("li.match"):
            found = re.search(r"ottelu=(\d+)", href_of(item))
            if found:
                playoff_ids.add(found.group(1))
            date_node = item.select_one("div.ml_pvm") or item.select_one("div.ml_pvmsiisti")
            if date_node is not None:
                iso = parse_date(clean_text(date_node), today)
                if iso:
                    playoff_dates.add(iso)
            time_node = item.select_one("div.ml_tulosklo")
            if time_node is not None:
                kickoff, _ = split_time_and_result(clean_text(time_node))
                if kickoff:
                    playoff_times.append(kickoff)

    # R6: jatkolohkojen omat sivut varalahteeksi, jos vahvistettu jatko-ottelu
    # ei nayttaydy joukkueen omassa otteluohjelmassa
    block_urls: list[str] = []
    for link in soup.select("a[href*='lohko=']"):
        if "jatko" not in clean_text(link).lower():
            continue
        url = requests.compat.urljoin("https://hjkcup.fi/taso/", link.get("href", ""))
        if url not in block_urls:
            block_urls.append(url)

    return {
        "games": extract_games(soup, series, today, playoff_ids),
        "playoff_dates": sorted(playoff_dates),
        "playoff_time_range": [min(playoff_times), max(playoff_times)] if playoff_times else None,
        "block_urls": block_urls,
    }


def parse_block_page(html: str, series: str, today: dt.date) -> list[dict[str, Any]]:
    """Jatkolohkon oma sivu: kaikki sen ottelut ovat jatko-otteluita."""
    soup = BeautifulSoup(html, "html.parser")
    return extract_games(soup, series, today, force_stage="jatko")


def needs_block_lookup(games: list[dict[str, Any]], page: dict[str, Any]) -> bool:
    """R6: lohko-sivut haetaan vain otteluparien ratkeamisikkunassa."""
    if not page["playoff_dates"] or not page["block_urls"]:
        return False
    if any(game["stage"] == "jatko" for game in games):
        return False  # jatko-ottelu on jo vahvistunut joukkuesivulle
    group = [game for game in games if game["stage"] == "lohko"]
    if not group or any(not game["played"] for game in group):
        return False  # lohkovaihe kesken, ei ole mita ratketa
    return True


def merge_games(
    games: list[dict[str, Any]], extra: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Yhdistaa ottelut pysyvalla tunnisteella, jottei sama ottelu tule kahdesti."""
    known = {game["id"] for game in games}
    for game in extra:
        if game["id"] not in known:
            known.add(game["id"])
            games.append(game)
    return sort_games(games)


def playoff_state(
    games: list[dict[str, Any]], page: dict[str, Any], today: dt.date
) -> dict[str, Any]:
    """R4: sarjakohtainen tieto tulevista jatko-otteluista, ilman spekulaatiota."""
    dates = page["playoff_dates"]
    upcoming = [date for date in dates if date >= today.isoformat()]
    confirmed = any(game["stage"] == "jatko" for game in games)
    return {
        "pending": bool(upcoming) and not confirmed,
        "dates": dates,
        "upcoming_dates": upcoming,
        "time_range": page["playoff_time_range"],
    }


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
            page = parse_team_page(fetch_html(session, url), series, today)
            games = page["games"]
            if not games:
                # R8: onnistunut mutta tyhja haku on virhe, ei tyhjennys
                raise ValueError("otteluita ei loytynyt sivulta")

            # R6: jatkolohkojen sivut haetaan vain ratkeamisikkunassa
            if needs_block_lookup(games, page):
                for block_url in page["block_urls"]:
                    time.sleep(args.delay)
                    try:
                        extra = parse_block_page(fetch_html(session, block_url), series, today)
                    except Exception as error:
                        print(f"[HUOM] {series}: jatkolohkon haku epaonnistui ({error})", file=sys.stderr)
                        continue
                    if extra:
                        print(f"[OK] {series}: jatkolohkosta {len(extra)} ottelua ({block_url})")
                        games = merge_games(games, extra)

            carry_over_times(games, old_games)
            playoffs = playoff_state(games, page, today)
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
                "playoffs": old.get("playoffs") if isinstance(old, dict) else None,
            }
            continue

        jatko = sum(1 for game in games if game["stage"] == "jatko")
        avoin = sum(1 for game in games if not game["opponent_confirmed"])
        print(
            f"[OK] {series}: {len(games)} ottelua "
            f"(jatko-otteluita {jatko}, vastustaja avoin {avoin}, "
            f"jatko tulossa: {'kylla' if playoffs['pending'] else 'ei'})"
        )
        series_data[series] = {
            "team_id": team_id,
            "url": url,
            "ok": True,
            "error": None,
            "fetched_at": now.isoformat(timespec="seconds"),
            "stale": False,
            "games": games,
            "playoffs": playoffs,
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
