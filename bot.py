import asyncio
import csv
import io
import os
import re
from datetime import datetime

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, BufferedInputFile
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PAN_API_URL = os.getenv(
    "PAN_API_URL",
    "https://api.paanel.shop/api/gateway.php"
).strip()
PAN_API_KEY = os.getenv("PAN_API_KEY", "").strip()

# Keep concurrency conservative. Increase only if your API provider permits it.
CONCURRENCY = max(1, int(os.getenv("CONCURRENCY", "5")))
REQUEST_TIMEOUT = max(5, int(os.getenv("REQUEST_TIMEOUT", "30")))
MAX_RETRIES = max(0, int(os.getenv("MAX_RETRIES", "2")))

PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.I)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not PAN_API_KEY:
    raise RuntimeError("PAN_API_KEY is missing")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


def extract_pans(text: str):
    """Extract unique PANs while preserving input order."""
    found = PAN_RE.findall((text or "").upper())
    seen = set()
    result = []
    for pan in found:
        if pan not in seen:
            seen.add(pan)
            result.append(pan)
    return result


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


async def validate_pan(session: aiohttp.ClientSession, pan: str, sem: asyncio.Semaphore):
    async with sem:
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with session.get(
                    PAN_API_URL,
                    params={"key": PAN_API_KEY, "advpan": pan},
                ) as resp:
                    if resp.status == 429:
                        if attempt < MAX_RETRIES:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        return None

                    if resp.status >= 500:
                        if attempt < MAX_RETRIES:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        return None

                    if resp.status != 200:
                        return None

                    payload = await resp.json(content_type=None)

                    # Expected shape from the supplied API:
                    # {"success":true, "data":{"data":{...}, "isValidPAN":true}}
                    outer = payload.get("data") or {}
                    record = outer.get("data") or {}
                    is_valid = outer.get("isValidPAN") is True

                    if not is_valid:
                        return None

                    return {
                        "PAN": clean(record.get("pan_number") or pan).upper(),
                        "Full Name": clean(record.get("full_name")),
                        "Father Name": clean(record.get("fname")),
                        "DOB": clean(record.get("dob")),
                    }

            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None

    return None


async def process_pans(pans, status_message: Message):
    sem = asyncio.Semaphore(CONCURRENCY)
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    headers = {"User-Agent": "PAN-Bulk-Checker/1.0"}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        tasks = [
            asyncio.create_task(validate_pan(session, pan, sem))
            for pan in pans
        ]

        results = []
        completed = 0

        for task in asyncio.as_completed(tasks):
            result = await task
            completed += 1
            if result:
                results.append(result)

            if completed == len(pans) or completed % 10 == 0:
                try:
                    await status_message.edit_text(
                        f"⏳ Checking PANs...\n\n"
                        f"Processed: {completed}/{len(pans)}\n"
                        f"Valid found: {len(results)}"
                    )
                except Exception:
                    pass

        # Preserve original PAN input order in final CSV.
        order = {pan: i for i, pan in enumerate(pans)}
        results.sort(key=lambda x: order.get(x["PAN"], 10**9))

        return results


def make_csv(rows):
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["PAN", "Full Name", "Father Name", "DOB"],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


async def handle_pans(message: Message, pans):
    if not pans:
        await message.answer(
            "❌ Koi valid PAN format nahi mila.\n\n"
            "Example:\n"
            "EQIPK8210A\n"
            "ABCDE1234F"
        )
        return

    # Avoid accidentally hammering the API.
    if len(pans) > 5000:
        await message.answer("❌ Ek batch me maximum 5000 PAN allowed hain.")
        return

    status = await message.answer(
        f"⏳ PAN checking start...\n\n"
        f"Total PAN: {len(pans)}\n"
        f"Valid found: 0"
    )

    rows = await process_pans(pans, status)

    if not rows:
        await status.edit_text(
            f"❌ Processing complete.\n\n"
            f"Checked: {len(pans)}\n"
            f"Valid PAN: 0"
        )
        return

    csv_bytes = make_csv(rows)
    filename = f"valid_pan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    await status.edit_text(
        f"✅ Processing complete!\n\n"
        f"Checked: {len(pans)}\n"
        f"Valid PAN: {len(rows)}\n\n"
        f"📥 CSV bhej raha hoon..."
    )

    document = BufferedInputFile(csv_bytes, filename=filename)
    await message.answer_document(
        document=document,
        caption=(
            f"✅ Valid PAN CSV\n"
            f"Total checked: {len(pans)}\n"
            f"Valid records: {len(rows)}"
        ),
    )


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 PAN Bulk Checker\n\n"
        "PAN numbers directly type/paste karo ya .txt file upload karo.\n\n"
        "Example:\n"
        "EQIPK8210A\n"
        "ABCDE1234F\n"
        "AAAAA1111A\n\n"
        "Sirf API se valid PAN records CSV me milenge.\n"
        "CSV columns: PAN, Full Name, Father Name, DOB"
    )


@dp.message(F.document)
async def txt_file(message: Message):
    document = message.document

    if not document.file_name.lower().endswith(".txt"):
        await message.answer("❌ Sirf .txt file upload karo.")
        return

    if document.file_size and document.file_size > 2 * 1024 * 1024:
        await message.answer("❌ TXT file maximum 2 MB honi chahiye.")
        return

    file = await bot.get_file(document.file_id)
    buffer = io.BytesIO()
    await bot.download_file(file.file_path, buffer)

    text = buffer.getvalue().decode("utf-8-sig", errors="ignore")
    pans = extract_pans(text)
    await handle_pans(message, pans)


@dp.message(F.text)
async def typed_pans(message: Message):
    pans = extract_pans(message.text or "")
    await handle_pans(message, pans)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
