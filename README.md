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
"best effort". Tässä repossa mitatut todelliset välit cron-ajojen välillä ovat
olleet **1 h 42 min – 4 h 40 min**, eivät 5 minuuttia. Siksi workflow ei luota
croniin ajan mittaamiseen:

- cron `*/5 * * * *` **käynnistää** ajon aina kun GitHub sen laukaisee,
- yksi ajo **kiertää itse 5 minuutin välein 350 minuuttia** (≈ 5 h 50 min),
- `concurrency: cancel-in-progress: true` varmistaa, että uusi käynnistys
  korvaa edellisen silmukan eikä jonoon kerry ajoja.

Kesto on mitoitettu pidemmäksi kuin cronin pisin havaittu väli, joten hakuun ei
jää katkoja. Aiempi 50 minuutin kesto kattoi vain noin 28 % ajasta, ja
turnauspäivänä yhden pelin tulos jäi kokonaan hakematta cron-katkoon.

Actionsin jobin enimmäiskesto on 6 h, joten 350 on käytännön maksimi; skripti
rajaa suuremmat arvot siihen automaattisesti.

Commit syntyy joka kierroksella, koska `games.json` sisältää hakuaikaleiman.
Sivun "Päivitetty"-rivi kertoo siis todella milloin tiedot on haettu.

### Turnauksen jälkeen

Ajo pyörii käytännössä yhtäjaksoisesti ja tekee commitin viiden minuutin
välein. Kun turnaus on ohi, workflow kannattaa laittaa pois päältä
(Actions → Päivitä pelitiedot → `···` → Disable workflow).
