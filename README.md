# Ilves HJK Cupissa

Mobiiliystävällinen turnausseurantasivu Ilveksen seitsemälle peliryhmälle
HJK Cupissa (turnaus `hjk_0031`).

Sivu: https://wessmanjere.github.io/IlvesHJKCup/

## Rakenne

| Polku | Kuvaus |
| --- | --- |
| `scraper/fetch_games.py` | Hakee ottelut hjkcup.fi:n taso-sivuilta ja kirjoittaa `docs/data/games.json`. |
| `.github/workflows/update.yml` | Ajaa scraperin 5 minuutin välein ja committaa muuttuneen datan. |
| `docs/index.html` | Yhden tiedoston sivu (CSS + JS mukana), lukee `docs/data/games.json`. |
| `docs/data/games.json` | Ajossa syntyvä pelidata aikaleimalla. |

## Peliryhmät

U9, U10, U11, U12, TU11, TU12, TU13 — joukkue-id:t ovat `scraper/fetch_games.py`:n
`TEAMS`-listassa.

## Scraperin ajaminen paikallisesti

```bash
python3 -m venv .venv
.venv/bin/pip install -r scraper/requirements.txt
.venv/bin/python scraper/fetch_games.py
```

## Huomioita

- hjkcup.fi palauttaa uudelle sessiolle ensin JS-uudelleenohjauksen ja asettaa
  `TASO_`-evästeen. Scraper hoitaa tämän automaattisesti hakemalla sivun uudelleen.
- Pyyntöjen välissä on 2 sekunnin viive, ja kaikki 7 sivua haetaan yhdellä ajolla
  (n. 14 s). 5 minuutin tahdilla se on noin 84 sivupyyntöä tunnissa.
- Jos yksittäisen sarjan haku epäonnistuu, sen aiemmin haettu data säilyy ja
  sivulla näytetään huomautus. Koko ajo ei kaadu.
- Sivusto näyttää pelatun ottelun tuloksen kellonajan tilalla, joten scraper
  säilyttää aiemmin haetun alkamisajan tuloksen rinnalla.

## Päivitystahti

Haku pyörii cronilla 5 minuutin välein — se on GitHub Actionsin lyhyin sallittu
cron-väli. Käytännössä GitHub jonottaa cron-ajoja ruuhka-aikoina, joten todellinen
väli voi ajoittain venyä. Turnauspäivinä haun voi käynnistää käsin *Run workflow*
-napista.

Commit syntyy vain kun `docs/data/games.json` on muuttunut, joten tyhjät ajot eivät
kerrytä historiaa.
