# MediaHub

MediaHub — Telegram bot orqali public Instagram Reel, video, rasm va carousel media’larini yuklab beruvchi MVP.

## Hozirgi imkoniyatlar

- Instagram URL validatsiyasi;
- public Reel, video, rasm va carousel uchun downloader adapteri;
- stream-first Telegram upload (`URLInputFile`);
- stream ishlamasa, chunked temporary-file fallback;
- Redis queue va cheklangan worker pool;
- 100+ parallel so‘rovda queue limit, rate limit va backpressure;
- foydalanuvchi uchun faol job limiti va kunlik limit;
- retry/fallback, timeout, cleanup va xatolik xabarlari;
- `/health` endpoint;
- Telegram webhook va webhook-secret validation.

Private kontent, login ma’lumotlarini yig‘ish yoki Instagram himoyasini chetlab o‘tish funksiyalari yo‘q.

## Ishga tushirish

1. Telegram’da bot yarating va token oling.
2. `.env` ichidagi `TELEGRAM_BOT_TOKEN` qiymatini to‘ldiring.
3. Servislarni ishga tushiring:

```powershell
docker compose up --build
```

Health-check:

```text
http://localhost:8080/health
```

## Lokal polling rejimi

Python 3.12 va Redis kerak bo‘ladi.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.bot
python -m app.worker
```

`.env` lokal rejimda `REDIS_URL=redis://localhost:6379/0` bo‘lishi kerak.

## Webhook rejimi

Webhook uchun public HTTPS URL va maxfiy secret kerak:

```env
PUBLIC_BASE_URL=https://your-domain.example
WEBHOOK_PATH=/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=kamida-16-belgidan-iborat-maxfiy-string
```

Ishga tushirish:

```powershell
uvicorn app.webhook:app --host 0.0.0.0 --port 8080
python -m app.worker
```

Telegram webhook faqat HTTPS URL’ga ulanadi. AlwaysData service sozlamalari uchun [DEPLOY_ALWAYSDATA.md](DEPLOY_ALWAYSDATA.md) fayliga qarang.

## Testlar

```powershell
pytest
```

## Muhim arxitektura qarori

Bot process’i faqat URL’ni validatsiya qilib, job’ni Redis queue’ga qo‘shadi. Og‘ir downloader va Telegram upload ishlari worker process’ida bajariladi. Bu 100 ta foydalanuvchi birdan link yuborganda bot update loop’ining qotib qolishining oldini oladi.

Avval `URLInputFile` orqali to‘g‘ridan-to‘g‘ri stream upload qilinadi. Bu ishlamasa, media cheklangan bufferlar bilan vaqtinchalik faylga yoziladi va upload tugagach darhol o‘chiriladi.

## Keyingi bosqichlar

- PostgreSQL’da foydalanuvchi va download tarixini saqlash;
- admin panel va statistika;
- media group uchun optimallashtirilgan yuborish;
- monitoring va alertlar;
- yanada to‘liq integration testlar;
- downloader adapterlarini alohida provider interfeysiga ajratish.

AlwaysData’ga joylashtirish bo‘yicha batafsil ko‘rsatma: [DEPLOY_ALWAYSDATA.md](DEPLOY_ALWAYSDATA.md)
