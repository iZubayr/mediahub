# MediaHub'ni AlwaysData'ga joylashtirish (Supabase Postgres bilan, Redis'siz)

AlwaysData Free/Shared tarifida Redis'ni SSH orqali compile qilish RAM
yetishmasligi tufayli barqaror ishlamaydi (`ld terminated with signal 9`
xatosi shundan). Shu sababli bu versiyada Redis butunlay olib tashlangan va
o'rniga siz allaqachon ishlatayotgan **Supabase Postgres** ishlatiladi:

- Navbat (queue) — `mediahub_jobs` jadvali, `SELECT ... FOR UPDATE SKIP LOCKED`
  orqali (Postgres'dagi standart, ishonchli job-queue patterni).
- Rate limit va foydalanuvchi limitlari — `mediahub_rate_minute`,
  `mediahub_rate_daily`, `mediahub_active_jobs` jadvallari.
- Jadvallar birinchi ishga tushishda avtomatik yaratiladi (`app/db.py`).

Hech qanday qo'shimcha compile, Service yoki Redis kerak emas — faqat ikkita
narsa kerak: **Webhook (Site)** va **Worker (Service)**, ikkalasi ham bitta
Supabase bazasiga ulanadi.

## 1. Supabase tayyorlash

1. Supabase loyihangiz Dashboard > **Project Settings > Database** ga o'ting.
2. **Connection string** bo'limidan **Session pooler** (yoki Transaction
   pooler) manzilini oling — bu manzil `pgbouncer` orqali ishlaydi va ko'p
   qisqa muddatli ulanishlar (bizning holatimizda ideal) uchun mos.
3. Format taxminan shunday bo'ladi:
   ```
   postgresql://postgres.xxxxxxxx:PAROL@aws-0-region.pooler.supabase.com:6543/postgres
   ```
4. Parolni URL-encode qiling agar maxsus belgilar bo'lsa (`@`, `#`, va h.k.).

## 2. Fayllarni serverga yuklash

```bash
cd /home/zubayr
git clone git@github.com:iZubayr/mediahub.git
cd mediahub
```

## 3. Python environment

Dashboard'da **Environment > Python** bo'limidan versiyani 3.12 qiling.

```bash
cd /home/zubayr/mediahub
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
mkdir -p tmp
chmod 700 tmp
```

## 4. `.env` sozlamalari

```env
TELEGRAM_BOT_TOKEN=YANGI_TOKEN_BOTFATHERDAN
DATABASE_URL=postgresql://postgres.xxxxxxxx:PAROL@aws-0-region.pooler.supabase.com:6543/postgres

PUBLIC_BASE_URL=https://zubayr.alwaysdata.net
WEBHOOK_PATH=/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=kamida-16-belgili-tasodifiy-string
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8080

MAX_QUEUE_SIZE=500
WORKER_CONCURRENCY=4
POLL_INTERVAL_SECONDS=1.5
STUCK_JOB_TIMEOUT_SECONDS=600

REQUESTS_PER_MINUTE=10
MAX_ACTIVE_JOBS_PER_USER=2
DAILY_DOWNLOAD_LIMIT=100

MAX_MEDIA_SIZE_MB=50
DOWNLOAD_TIMEOUT_SECONDS=120
UPLOAD_TIMEOUT_SECONDS=180
RETRY_ATTEMPTS=2
TEMP_DIR=/home/zubayr/mediahub/tmp
INSTAGRAM_COOKIES_FILE=

ADMIN_IDS=your_numeric_telegram_id
```

Majburiy obuna kanallari endi `.env`da emas — bot ishga tushgach, Telegram'da
o'zingizga (admin sifatida) yozing:

```
/addchannel @your_channel_username
```

yoki yopiq kanal uchun uning `-100...` bilan boshlanuvchi ID'sini yuboring.
Kanalni qo'shishdan oldin **botni o'sha kanalga admin qilib qo'shing** —
bot buni tekshiradi va admin bo'lmasa xato qaytaradi (shu bilan keyinchalik
"hamma foydalanuvchi bloklanib qoladi" degan holatning oldi olinadi).

Boshqa buyruqlar:
- `/channels` — hozirgi ro'yxatni ko'rish
- `/removechannel N` — `/channels` ro'yxatidagi N-raqamli kanalni o'chirish

`ADMIN_IDS`ni bilish uchun Telegram'da @userinfobot'ga yozing — u sizga raqamli ID'ingizni beradi.

```bash
chmod 600 /home/zubayr/mediahub/.env
```

**Muhim:** yuqoridagi token bir marta chatda ochiq yozilgan edi — uni
BotFather'da (`/revoke` yoki yangi token so'rash) albatta almashtiring, keyin
faqat shu `.env` faylida saqlang.

`WORKER_CONCURRENCY=4` — 100 kishilik yuklama uchun boshlang'ich qiymat.
Agar Supabase bazasida ulanish limitiga tegib qolsangiz (Free tarifda odatda
~60 ulanish), buni pasaytiring yoki pooler manzilini albatta ishlatganingizga
ishonch hosil qiling.

## 5. Webhook — Site sifatida

Dashboard > **Web > Sites > Add a site**:

- Address: `zubayr.alwaysdata.net`
- Type: `User program`
- Command:
  ```
  /home/zubayr/mediahub/.venv/bin/uvicorn app.webhook:app --host $IP --port $PORT
  ```
- Working directory: `/home/zubayr/mediahub`

`$IP` va `$PORT`ni AlwaysData avtomatik beradi, o'zgartirmang.

## 6. Worker — Service sifatida

Dashboard > **Advanced > Services > Add a service**:

- Name: `mediahub-worker`
- Command:
  ```
  /home/zubayr/mediahub/.venv/bin/python -m app.worker
  ```
- Working directory: `/home/zubayr/mediahub`

Worker to'xtab qolsa, AlwaysData uni avtomatik qayta ishga tushiradi.

## 7. Tekshirish

SSH orqali baza ulanishini tekshiring:

```bash
cd /home/zubayr/mediahub
. .venv/bin/activate
python -c "
import asyncio
from app.config import Settings

async def check():
    import asyncpg
    settings = Settings()
    conn = await asyncpg.connect(settings.database_url)
    print(await conn.fetchval('SELECT 1'))
    await conn.close()

asyncio.run(check())
"
```

`1` chiqsa — ulanish ishlayapti.

Keyin:
- `https://zubayr.alwaysdata.net/health` — javobda `"database": "ok"` va
  `"mode": "webhook"` chiqishi kerak.
- Dashboard > **Advanced > Processes > Services** bo'limidan
  `mediahub-worker` holatini kuzating.
- Telegram'da botga `/start`, so'ng public Instagram Reel havolasini yuboring.

## 8. 100 kishilik yuklama haqida eslatma

- Navbat va limitlar endi Redis emas, Supabase orqali ishlaydi — bu biroz
  sekinroq (har so'rov tarmoq orqali Supabase'ga boradi), lekin AlwaysData
  Free/Shared'da ancha barqaror, chunki hech narsa compile qilinmaydi va
  RAM'ga bog'liq emas.
- Agar keyinchalik yuklama sezilarli oshsa (masalan minglab foydalanuvchi),
  o'shanda alohida VPS'ga o'tib, haqiqiy Redis qo'shish mantiqan to'g'ri
  bo'ladi — lekin 100 kishi uchun bu arxitektura yetarli.
- `STUCK_JOB_TIMEOUT_SECONDS` — agar worker ishlab turgan paytda qulab tushsa
  yoki qayta ishga tushsa, "processing" holatida qolib ketgan joblar shu
  vaqtdan keyin avtomatik qayta navbatga qo'shiladi.

## 9. Ehtimoliy xatolar

- `RuntimeError: DATABASE_URL is not configured` — `.env` fayli topilmayapti
  yoki bo'sh; working directory to'g'riligini tekshiring.
- `too many connections` (Supabase xatosi) — pooler manzilidan
  foydalanayotganingizni tekshiring (`:6543` porti, `:5432` emas), yoki
  `WORKER_CONCURRENCY`ni kamaytiring.
- `ModuleNotFoundError` — `.venv` faollashtirilmagan yoki
  `pip install -r requirements.txt` bajarilmagan.
- `You need to log in` — story yoki private kontent login talab qilmoqda,
  bu kutilgan xatti-harakat.
- Worker ishlamayapti — Service loglarini va Supabase bazasidagi
  `mediahub_jobs` jadvalini tekshiring (`SELECT * FROM mediahub_jobs;`).

## Rasmiy hujjatlar

- AlwaysData Python: https://help.alwaysdata.com/en/docs/web-hosting/languages/python/configuration/
- AlwaysData Services: https://help.alwaysdata.com/en/docs/web-hosting/services/
- Supabase Database connection: https://supabase.com/docs/guides/database/connecting-to-postgres
