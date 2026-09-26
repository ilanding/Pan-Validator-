# PAN Bulk Checker — Telegram + Railway

Telegram bot that accepts PAN numbers by text or `.txt` file and creates a CSV containing **only records for which the API returns `isValidPAN: true`**.

## Output columns

- PAN
- Full Name (`full_name`)
- Father Name (`fname`)
- DOB (`dob`)

Other API fields such as phone, email, address and masked Aadhaar are not written to the output CSV.

## 1. Create Telegram bot

Open Telegram → `@BotFather` → `/newbot` → copy the bot token.

## 2. Deploy on Railway

Create a new Railway service from this project/repository.

Set these Variables in Railway:

```text
BOT_TOKEN=your Telegram bot token
PAN_API_URL=https://api.paanel.shop/api/gateway.php
PAN_API_KEY=your API key
CONCURRENCY=5
REQUEST_TIMEOUT=30
MAX_RETRIES=2
```

Do not put the API key directly in `bot.py` or commit it to GitHub.

## 3. Use the bot

Send:

```text
EQIPK8210A
ABCDE1234F
AAAAA1111A
```

or upload a `.txt` file:

```text
EQIPK8210A
ABCDE1234F
AAAAA1111A
```

The bot returns a CSV containing only valid API results.

## Notes

- PAN format is checked locally before making API calls.
- Duplicate PANs in the same batch are removed.
- Requests are rate-limited with controlled concurrency.
- Temporary 429/5xx/network failures are retried.
- Maximum batch size: 5000 PANs.
- The API provider's terms, authorization, rate limits, and applicable privacy/data-protection requirements should be followed.
