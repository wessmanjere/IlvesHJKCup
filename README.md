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
- Eri taso-asennukset käyttävät eri luokkanimiä samoille kentille
  (`ml_pvm` / `ml_pvmsiisti`, `ml_kenttanimi` / `ml_kentta`), joten parsinta
  kokeilee vaihtoehdot järjestyksessä. Testattu sekä pelaamattomia otteluita
  vasten (hjkcup.fi) että pelattuja vasten
  (paasiaisturnaus.torneopal.fi, `ilvesjp_0024`).
- Tulos tulee muodossa `2–1` (en dash) ja normalisoidaan muotoon `2 - 1`.
  Pelattu-tila luetaan tuloksesta tai `li.match.played`-luokasta.
- `games.json` säilyttää tuloksen sivuston virallisessa muodossa koti–vieras.
  Sivu kääntää luvut vieraspeleissä Ilves-ensin, koska kortin otsikko on
  "Ilves vs vastustaja". Kääntö tehdään vain puhtaalle `n - n` -tulokselle;
  poikkeavat merkinnät näytetään sellaisenaan.
- Päivämäärästä puuttuu vuosi, joten se päätellään valitsemalla ajallisesti
  lähin vaihtoehto kuluvasta, edellisestä ja seuraavasta vuodesta.

## Päivitystahti

Haku pyörii 5 minuutin välein. GitHubin cron **ei** yksin riitä tähän: se on
"best effort" eikä laukea luotettavasti tiheillä väleillä — tässä repossa se ei
lauennut kertaakaan ensimmäisen 95 minuutin aikana. Siksi workflow ei luota
croniin:

- cron `*/5 * * * *` **käynnistää** ajon aina kun GitHub sen laukaisee,
- yksi ajo **kiertää itse 5 minuutin välein** enintään 50 minuuttia,
- `concurrency: cancel-in-progress: true` varmistaa, että uusi käynnistys
  korvaa edellisen silmukan eikä jonoon kerry ajoja.

Näin päivitys jatkuu 5 minuutin tahdissa vaikka cron laukeaisi vain kerran
tunnissa — tai vaikka ei lainkaan, kun ajo käynnistetään käsin.

### Turnauspäivä

Käynnistä ajo käsin *Run workflow* -napista ja anna `duration_minutes`-kentälle
esim. `350`. Yksi käynnistys kattaa silloin lähes kuusi tuntia yhtäjaksoista
5 minuutin päivitystä (Actionsin jobin enimmäiskesto on 6 h).

Commit syntyy joka kierroksella, koska `games.json` sisältää hakuaikaleiman.
Sivun "Päivitetty"-rivi kertoo siis todella milloin tiedot on haettu.
