# Ilves HJK Cupissa

Mobiiliystävällinen turnausseurantasivu Ilveksen seitsemälle peliryhmälle
HJK Cupissa (turnaus `hjk_0031`).

Sivu: https://wessmanjere.github.io/IlvesHJKCup/

## Rakenne

| Polku | Kuvaus |
| --- | --- |
| `scraper/fetch_games.py` | Hakee ottelut hjkcup.fi:n taso-sivuilta ja kirjoittaa `docs/data/games.json`. |
| `.github/workflows/update.yml` | Ajaa scraperin 2 minuutin välein ja committaa muuttuneen datan. |
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
- Pyyntöjen välissä on 2 sekunnin viive, ja kaikki 7 sivua haetaan yhdellä kierroksella
  (n. 14 s). 2 minuutin tahdilla se on noin 210 sivupyyntöä tunnissa.
- Jos yksittäisen sarjan haku epäonnistuu, sen aiemmin haettu data säilyy ja
  sivulla näytetään huomautus. Koko ajo ei kaadu.
- Sivusto näyttää pelatun ottelun tuloksen kellonajan tilalla, joten scraper
  säilyttää aiemmin haetun alkamisajan tuloksen rinnalla.

## Päivitystahti

Haku pyörii 2 minuutin välein. GitHub Actionsin cron ei tue tätä suoraan — lyhyin
sallittu cron-väli on 5 minuuttia — joten workflow on rakennettu näin:

- cron `*/5 * * * *` käynnistää ajon,
- yksi ajo kiertaa sisäisesti 2 minuutin välein enintään 9 minuuttia,
- `concurrency: cancel-in-progress: true` varmistaa, että uusi cron-ajo korvaa
  edellisen silmukan eikä jonoon kerry ajoja.

Näin haku tapahtuu 2 minuutin tahdissa myös silloin kun GitHub viivästyttää cronia:
edellinen ajo jatkaa kiertämistä 9 minuuttiin asti.

Väliä voi säätää ajokohtaisesti *Run workflow* -napin kentistä `interval_seconds`
ja `duration_minutes`.

**Huomio GitHub Pagesista:** branch-pohjaisessa julkaisussa on pehmeä raja noin
10 buildia tunnissa. Jos tulokset muuttuvat tiheästi, commitit voivat ylittää tämän
ja Pages-julkaisu hidastuu, vaikka `games.json` päivittyisi repoon ajallaan.
