# MediaHub’ni AlwaysData Free’ga joylashtirish

Ushbu loyiha AlwaysData’da Telegram webhook va Redis worker bilan ishlaydi. Shuning uchun bitta HTTP User Program va bitta background service kerak:

1. `mediahub-webhook` — Telegram update’larni HTTPS orqali qabul qiladi.
2. `mediahub-worker` — Redis queue’dan vazifalarni olib, Instagram media’ni yuklaydi va Telegram’ga yuboradi.

AlwaysData free planida Docker’ga tayanilmaydi. Python paketlari SSH orqali virtual environment ichiga o‘rnatiladi. AlwaysData Python uchun `python -m pip install -r requirements.txt` usulini va foreground service’larni qo‘llab-quvvatlaydi.

## 1. Fayllarni serverga yuklash

SSH yoki SFTP orqali `mediahub` papkasini account home directory’ga yuklang:

```bash
cd /home/ACCOUNT
git clone YOUR_REPOSITORY_URL mediahub
cd mediahub
```

Repository ishlatilmasa, `app/`, `requirements.txt`, `.env`, `plan.md` va `pytest.ini` fayllarini SFTP orqali yuklash mumkin.

## 2. Python environment

AlwaysData’da Python versiyasini 3.12 qilib tanlang: `Environment > Python`.

SSH terminalda:

```bash
cd /home/ACCOUNT/mediahub
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
mkdir -p tmp
chmod 700 tmp
```

## 3. Redis service

Free/Public Cloud’da Redis’ni account ichida alohida service sifatida compile qilish mumkin:

```bash
cd /home/ACCOUNT
mkdir -p redis
cd redis
wget -O- https://download.redis.io/redis-stable.tar.gz | tar -xz --strip-components=1
make
```

AlwaysData panelida `Advanced > Services > Add` orqali Redis service yarating:

- Name: `mediahub-redis`
- Command: `./src/redis-server --bind :: --port 8300 --protected-mode no`
- Working directory: `/home/ACCOUNT/redis`
- Monitoring command: `./src/redis-cli -h services-ACCOUNT.alwaysdata.net -p 8300 ping`

Redis tashqi service hostname orqali ulanadi:

```env
REDIS_URL=redis://services-ACCOUNT.alwaysdata.net:8300/0
```

Redis’ni parolsiz ochiq qoldirish tavsiya etilmaydi. Redis ACL’da parol o‘rnatilgandan keyin:

```env
REDIS_URL=redis://default:REDIS_PASSWORD@services-ACCOUNT.alwaysdata.net:8300/0
```

## 4. `.env` sozlamalari

Serverdagi `/home/ACCOUNT/mediahub/.env` fayliga quyidagilarni yozing:

```env
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
REDIS_URL=redis://default:REDIS_PASSWORD@services-ACCOUNT.alwaysdata.net:8300/0

QUEUE_NAME=mediahub:downloads
PROCESSING_QUEUE_NAME=mediahub:downloads:processing
MAX_QUEUE_SIZE=100
WORKER_CONCURRENCY=1
REQUESTS_PER_MINUTE=5
MAX_ACTIVE_JOBS_PER_USER=1
DAILY_DOWNLOAD_LIMIT=30
MAX_MEDIA_SIZE_MB=25
DOWNLOAD_TIMEOUT_SECONDS=120
UPLOAD_TIMEOUT_SECONDS=180
RETRY_ATTEMPTS=2
TEMP_DIR=/home/ACCOUNT/mediahub/tmp
INSTAGRAM_COOKIES_FILE=
```

```bash
chmod 600 /home/ACCOUNT/mediahub/.env
```

Free plan resurslari kichik bo‘lgani uchun AlwaysData’da `WORKER_CONCURRENCY=1` bilan boshlash tavsiya etiladi.

## 5. Webhook site

AlwaysData panelida `Web > Sites > Add a site` orqali `User program` tanlang:

- Address: `ACCOUNT.alwaysdata.net`
- Type: `User program`
- Command: `/home/ACCOUNT/mediahub/.venv/bin/uvicorn app.webhook:app --host $IP --port $PORT`
- Working directory: `/home/ACCOUNT/mediahub`

AlwaysData bergan `IP` va `PORT` environment variables’ini o‘zgartirmang. HTTPS sayt manzili webhook URL bo‘ladi:

```env
PUBLIC_BASE_URL=https://ACCOUNT.alwaysdata.net
WEBHOOK_PATH=/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=kamida-16-belgili-secret
```

## 6. Worker service

Yana bitta service yarating:

- Name: `mediahub-worker`
- Command: `/home/ACCOUNT/mediahub/.venv/bin/python -m app.worker`
- Working directory: `/home/ACCOUNT/mediahub`

Webhook User Program va worker service ishlayotgan bo‘lishi kerak. Worker service to‘xtab qolsa, AlwaysData uni avtomatik qayta ishga tushiradi.

## 7. Tekshirish

SSH orqali:

```bash
cd /home/ACCOUNT/mediahub
. .venv/bin/activate
python -c "import redis, os; print(redis.from_url(os.environ['REDIS_URL']).ping())"
```

Paneldagi `Advanced > Processes > Services` va service loglaridan `mediahub-bot` hamda `mediahub-worker` holatini ko‘ring.

`https://ACCOUNT.alwaysdata.net/health` manzilini tekshiring. Javobda `"mode": "webhook"` chiqishi kerak. Keyin Telegram’da `/start` yuboring va public Instagram Reel yoki rasm post havolasi bilan tekshiring.

## 8. Stories haqida muhim eslatma

Instagram story’lar ko‘pincha login talab qiladi. Public bo‘lsa ham downloader login so‘rashi mumkin. Bunday holatda bot endi umumiy xato emas, quyidagi aniq xabarni qaytaradi:

`Story olish uchun Instagram login cookie kerak.`

Cookie ishlatish kerak bo‘lsa, faqat o‘zingizga tegishli account cookie faylini xavfsiz joylashtiring va `.env`da yo‘lni ko‘rsating:

```env
INSTAGRAM_COOKIES_FILE=/home/ACCOUNT/mediahub/private/instagram-cookies.txt
```

```bash
mkdir -p /home/ACCOUNT/mediahub/private
chmod 700 /home/ACCOUNT/mediahub/private
chmod 600 /home/ACCOUNT/mediahub/private/instagram-cookies.txt
```

Cookie faylini Git’ga yubormang, bot loglariga chiqarmang va foydalanuvchilarga bermang. Cookie muddati tugashi yoki Instagram tomonidan bekor qilinishi mumkin.

## 9. Common errors

- `Connection refused` — Redis service ishlamayapti yoki `REDIS_URL` noto‘g‘ri.
- `ModuleNotFoundError` — `.venv` tanlanmagan yoki `pip install -r requirements.txt` bajarilmagan.
- `Permission denied` — `tmp` va private papkalar account user’iga tegishli emas.
- `You need to log in` — story yoki private kontent cookie/login talab qilmoqda.
- `Fayl juda katta` — `MAX_MEDIA_SIZE_MB` yoki Telegram limitiga yetilgan.
- Worker ishlamayapti — Redis queue va service loglarini tekshiring.

## Rasmiy AlwaysData hujjatlari

- Python: https://help.alwaysdata.com/en/docs/web-hosting/languages/python/configuration/
- Services: https://help.alwaysdata.com/en/docs/web-hosting/services/
- Redis: https://help.alwaysdata.com/en/docs/development/guides/redis/
- Docker: https://help.alwaysdata.com/en/docs/development/docker/
