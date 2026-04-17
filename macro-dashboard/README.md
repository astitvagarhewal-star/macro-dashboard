# Macro Dashboard India v2

A real-time financial dashboard for Indian markets with live data from Yahoo Finance, NSE India, and Investing.com.

## Features

- **Market Snapshot**: Live Nifty 50, Bank Nifty, India VIX, USD/INR, Brent, Gold, US 10Y, GSec 10Y, DXY
- **FII/DII Flows**: Foreign and Domestic Institutional Investor flows with 15-day history
- **Sector Performance**: Real-time sector data with 52-week position indicators
- **PCR (Put/Call Ratio)**: Options market sentiment analysis
- **Market Mood Index**: Fear/Greed indicator based on VIX, FII flows, breadth, and PCR
- **Economic Calendar**: Upcoming RBI, Macro, and Global events

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Serve dashboard HTML |
| `GET /api/snapshot` | Market snapshot with real-time prices |
| `GET /api/fii-dii` | FII/DII flows data |
| `GET /api/sectors` | Sector performance data |
| `GET /api/pcr` | Put/Call ratio data |
| `GET /api/mood` | Market mood index |
| `GET /api/calendar` | Economic calendar |

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python -m uvicorn main:app --reload
```

Or use the startup script:
```bash
# Windows
start.bat
```

## Data Sources

- **Yahoo Finance**: Nifty, Bank Nifty, VIX, commodities, forex
- **NSE India**: FII/DII flows, PCR data (option chain)
- **Investing.com**: India GSec 10Y yield

## Architecture

- **Backend**: FastAPI with 5-minute caching
- **Frontend**: Vanilla JavaScript with Chart.js
- **Styling**: Dark terminal-style UI with CSS Grid

## Error Handling

The dashboard uses fallback data when APIs fail:
- Green error dots indicate live data is being used
- Red error dots indicate fallback data is active

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+

## License

MIT
