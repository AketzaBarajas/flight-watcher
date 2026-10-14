# Decision log

Decisions behind flight-watcher, with the reason for each and what was ruled out.
The detailed rules (in Spanish) are in [guia-de-uso.md](guia-de-uso.md).

## Price sources

**Google Flights results page, parsed by our own code.** It covers every airline and also
returns Google's "typical price range" for a route, which is a useful second opinion.
`fast-flights` 3.1.0 is used to build the query, but its parser ignores the "best flights"
list, so the response is parsed in `vigilante/fuentes/google_flights.py`. The version is
pinned because the parser depends on how that release builds the request. From the EU the
request carries the cookie equivalent to "Reject all" on the consent screen.

**Ryanair's fare-finder endpoint for "anywhere".** One call returns the cheapest round trip
from an airport to every destination in a date range. No free equivalent was found for the
other airlines, so exploring "anywhere" is limited to Ryanair's network. Countries Ryanair
does not serve are only watched if the user picks specific cities, which go to Google.

**Ruled out (tested on 2026-10-13):**

- Google's price calendar endpoint: returned errors.
- Amadeus Self-Service API: shut down on 2026-07-17.
- SerpApi: kept as a paid fallback if the Google page parser breaks.

Neither source in use is an official API. Both can change without notice, and the tool
keeps to roughly 40 requests a day (up to 14 to Ryanair, 25 to Google by default).

## A rule-based agent, not a language model

The agent (`vigilante/agente.py`) plans, queries, remembers, decides and acts, but every step
is plain code. Whether a price deserves an alert is arithmetic over the price history, and a
rule-based loop is predictable, costs nothing to run every day and can be covered by unit tests.

## Alert rules tuned against noise

- **"Usual price"** is the median of the daily best price per destination and month, and it
  needs 5 days of history. A median ignores single spikes better than a mean.
- **Saved destinations** alert at or below the user's maximum, 15 % below usual, or below
  Google's typical range. **Everything else** only alerts at or below the bargain threshold
  or 35 % below usual: those are destinations the user did not ask about.
- **The default bargain threshold is 25 €.** That is below Ryanair's floor for a round trip
  (2 × 14.99 €) on purpose: at 35 € an alert arrived almost daily for prices that were normal.
- **No repeats:** an alert is sent again only if the price improves 10 % or three weeks pass.
  Each message carries at most 6 saved-destination alerts and 3 others, one per city.

## Scheduling that survives a PC that was off

The Windows task fires at login (after 5 minutes, so the network is up) and hourly from 08:00
to midnight, and the program runs with `--una-vez-al-dia`. Only the first successful run of the
day queries prices; later runs exit at once. If every query fails (for example, no network),
the day does not count and the next hour retries. A single 08:00 trigger would silently skip
days when the PC was off.

A GitHub Actions schedule was written as an alternative but not published. It would have to
commit `data/` back to the repository, and that data is personal.

## Local-only panel

The panel is a standard-library HTTP server bound to `127.0.0.1:8765`. It rejects any request
whose `Host` header is not the panel's own address, or whose `Origin` (if present) is not the
panel. That stops other websites open in the same browser from reading or changing the saved
destinations. Front-end libraries, the map and the font are served from the package, with no CDN.

## The panel shows every saved city, filtered in the browser

The agent used to keep only the 12 cheapest trips of each month for the panel, so most saved
cities never appeared. It now writes the best price of every destination and month it saw
(a few hundred rows, about 160 KB). The panel groups airports by city, picks the cheapest flight
for each saved city and applies the month, date, price and destination filters itself, so filtering
needs no new server endpoint.

Google answers one date per query, so it cannot price every saved city in every month each day
(about 45 cities x 7 months = 300 pairs). Each saved city and month is a gap. Gaps that today's
Ryanair results already fill are skipped. That includes cities Ryanair serves from other airports
but not from the user's, which earlier versions never sent to Google. The rest are queried with
the never-seen ones first, then the ones without a price for longest. A daily budget of 25 cycles
through every gap in about two weeks.
When a gap has no price today, the agent adds the last price seen for it, however old, taken from
the most recent day only: an older minimum says nothing about today's price. These rows carry the
day they were seen and never trigger alerts.

Saved cities are worked out in the browser from the current saved destinations, so a city marked
after the last search shows up straight away as "no price yet".

## Two languages and two themes without a framework

Panel strings live in `static/textos.js` as a Spanish and an English table; static HTML is tagged
with `data-i18n` attributes. Country names in English come from the browser
(`Intl.DisplayNames`), so only city names needed English data: an `en` field in the catalogue,
set only when the name differs, from Ryanair's English airport list plus a hand-made list. Errors
coming from the server's validation are still in Spanish. Alerts stay in Spanish.

Colours are CSS variables with a dark set. The page follows the system theme until the user picks
one; the choice (and the language) is stored in `localStorage`, and a small inline script applies
the theme before the stylesheet paints to avoid a flash.

## Plain files instead of a database

Price history and alert state are CSV and JSON files in `data/`. At a few dozen queries a day a
database adds setup without adding anything, and the files can be opened and checked by hand.
`data/`, `config.yaml` and `.env` are personal and are never committed; the repository ships
`config.example.yaml` and `.env.example` instead.
