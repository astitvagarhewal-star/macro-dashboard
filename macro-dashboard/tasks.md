# Macro Dashboard India — Task Tracker

## Active

- [x] Fix IDE false-positive syntax errors in `index.html` (added `// @ts-nocheck` to `<script>` block — VS Code was choking on `??` and `?.` in minified ES2020 JS)

---

## Refresh Loop (ralph loop)

> The auto-refresh mechanism: `setInterval(load, REFRESH)` where `REFRESH = 300000ms` (5 min)

- [ ] Show a countdown timer in the header so the user knows when the next refresh fires
- [ ] Add a manual "Refresh Now" button that calls `load()` and resets the interval
- [ ] On refresh, diff old vs new data and highlight changed cells briefly (flash green/red)
- [ ] Exponential backoff on failed fetches — don't hammer the API if the backend is down
- [ ] Persist last-successful data to `localStorage` so a page reload doesn't show skeletons

---

## Backend (`main.py`)

- [ ] `gsec10y` currently uses `^TNX` (US 10Y) as a proxy — replace with a real India G-Sec source
- [ ] FII/DII data is partially mocked — investigate reliable free NSE scraping or add a paid data option
- [ ] PCR data is fully simulated — connect to NSE options chain API when available
- [ ] Add `/api/health` endpoint for quick liveness checks
- [ ] Validate that `CACHE_TTL_SECONDS = 300` aligns with REFRESH interval on the frontend

---

## Frontend (`index.html`)

- [ ] Mobile layout: ticker bar hidden on small screens — consider a collapsed single-row summary instead
- [ ] Accessibility: add `aria-label` to icon-only elements (live dot, error dots)
- [ ] Dark-mode gauge colors could use a smoother gradient transition at the midpoint
- [ ] Consider splitting the monolithic `index.html` into separate CSS/JS files for maintainability

---

## Deployment

- [ ] `vercel.json` exists — verify FastAPI is deployable on Vercel (needs `@vercel/python` or serverless wrapper)
- [ ] Add environment variable support for API keys / data source URLs
- [ ] Set up a basic CI check (lint + syntax validation) before each deploy
