# MediaHub — loyiha rejasi

## 1. Loyiha maqsadi

Telegram bot orqali Instagram havolalaridan media kontentni yuklab beradigan xizmat yaratish.

Foydalanuvchi Instagram post, Reel, video, carousel va ruxsat etilgan story havolasini botga yuboradi. Bot havolani tekshiradi, media faylni oladi va Telegram orqali foydalanuvchiga qaytaradi.

## 2. Asosiy talablar

### 2.1. Telegram bot

- Foydalanuvchi `/start` buyrug‘i bilan xizmatdan foydalanishni boshlaydi.
- Bot foydalanuvchiga qisqa yo‘riqnoma va foydalanish qoidalarini ko‘rsatadi.
- Instagram havolasi yuborilganda bot uni avtomatik aniqlaydi.
- Noto‘g‘ri yoki qo‘llab-quvvatlanmaydigan havola yuborilsa, tushunarli xabar qaytariladi.
- Yuklash jarayonida foydalanuvchiga holat ko‘rsatiladi: `Tekshirilmoqda`, `Yuklanmoqda`, `Tayyor` yoki `Xatolik yuz berdi`.
- Tayyor fayl Telegram orqali yuboriladi.
- Foydalanuvchi `/help` orqali foydalanish bo‘yicha ma’lumot oladi.

### 2.2. Instagram kontent turlari

Bot quyidagi kontent turlarini qo‘llab-quvvatlashi kerak:

- Reels;
- oddiy video postlar;
- rasmli postlar;
- carousel postlar — bir nechta rasm yoki videoni alohida yoki arxiv ko‘rinishida yuborish;
- public story havolalari, agar texnik va huquqiy jihatdan ruxsat etilgan bo‘lsa;
- Instagram profil yoki post havolasidan media turini aniqlash.

Private akkauntlar, login talab qiladigan kontent yoki o‘chirilgan postlar dastlabki versiyada qo‘llab-quvvatlanmaydi.

### 2.3. Fayl bilan ishlash

- Video imkon qadar original yoki yuqori sifatda yuklanadi.
- Rasm original sifatga yaqin ko‘rinishda yuboriladi.
- Audio mavjud bo‘lsa, video bilan birga saqlanadi.
- Telegram fayl hajmi chekloviga yaqin fayllar uchun alohida xatolik xabari beriladi.
- Juda katta fayllar uchun serverda vaqtinchalik saqlash yoki siqish mexanizmi bo‘ladi.
- Vaqtinchalik fayllar yuborilgandan keyin avtomatik o‘chiriladi.

## 3. Tavsiya qilinadigan texnik arxitektura

### 3.1. Backend

Tavsiya etiladigan variant:

- Python;
- `aiogram` — Telegram bot uchun;
- `yt-dlp` yoki Instagram bilan ishlashga mos, qonuniy va barqaror downloader qatlam;
- `FastAPI` — health-check va admin API uchun;
- `Redis` — navbat, vaqtinchalik holat va rate limit uchun;
- `PostgreSQL` — foydalanuvchilar, yuklashlar va statistika uchun;
- `Docker` — muhitni bir xil saqlash va deploy qilish uchun.

### 3.2. Ishlash oqimi

1. Foydalanuvchi Instagram havolasini yuboradi.
2. Bot havolani validatsiya qiladi.
3. Bot foydalanuvchi limiti va fayl hajmi talablarini tekshiradi.
4. Yuklash vazifasi navbatga qo‘shiladi.
5. Worker media faylni yuklaydi.
6. Fayl tekshiriladi va zarur bo‘lsa qayta ishlanadi.
7. Bot faylni foydalanuvchiga yuboradi.
8. Vaqtinchalik fayl o‘chiriladi va natija log qilinadi.

## 4. Muhim funksiyalar

### Foydalanuvchi funksiyalari

- Instagram havolasidan yuklash;
- yuklash holatini ko‘rish;
- oxirgi yuklangan faylni qayta olish imkoniyati;
- til tanlash: o‘zbek tili asosiy, keyinchalik rus va ingliz tillari;
- foydalanish statistikasi yoki kunlik limit haqida ma’lumot olish;
- xatolik yuz berganda qayta urinib ko‘rish.

### Admin funksiyalari

- foydalanuvchilar sonini ko‘rish;
- kunlik yuklashlar va xatoliklar statistikasini ko‘rish;
- foydalanuvchini bloklash yoki blokdan chiqarish;
- foydalanuvchi limitlarini o‘zgartirish;
- texnik loglarni ko‘rish;
- downloader holatini tekshirish;
- majburiy kanalga obuna bo‘lish talabini boshqarish, agar keyinchalik kerak bo‘lsa.

## 5. Xavfsizlik va cheklovlar

- Bot tokeni `.env` faylida saqlanadi va Git repository’ga kiritilmaydi.
- Foydalanuvchi yuborgan URL faqat ruxsat etilgan Instagram domenlariga tegishli ekanligi tekshiriladi.
- SSRF va zararli URL hujumlariga qarshi himoya qo‘llanadi.
- Har bir foydalanuvchi uchun rate limit o‘rnatiladi.
- Bir foydalanuvchi bir vaqtning o‘zida haddan tashqari ko‘p yuklash boshlay olmaydi.
- Server diskini to‘ldirib yubormaslik uchun fayl hajmi va saqlash vaqti cheklanadi.
- Xatoliklarda maxfiy ma’lumotlar logga yozilmaydi.
- Downloader versiyasi va Instagram o‘zgarishlari muntazam nazorat qilinadi.

## 6. Huquqiy va platforma talablari

Bot faqat foydalanuvchi yuklash huquqiga ega bo‘lgan, ochiq va ruxsat etilgan kontent bilan ishlashi kerak. Instagram va Telegram foydalanish shartlari, mualliflik huquqi hamda shaxsiy ma’lumotlarni himoya qilish talablariga rioya qilinadi.

Botda qisqa ogohlantirish bo‘lishi tavsiya etiladi: foydalanuvchi yuklab olingan kontentdan foydalanish uchun javobgar ekanligi ko‘rsatiladi. Private kontentni chetlab o‘tish, login ma’lumotlarini yig‘ish yoki himoyani buzishga qaratilgan funksiyalar qo‘shilmaydi.

## 7. MVP — birinchi versiya

Birinchi ishlaydigan versiyada quyidagilar yetarli:

- Telegram botni ishga tushirish;
- public Reel va video postlarni yuklash;
- rasmli postlarni yuklash;
- carousel’ni qo‘llab-quvvatlash;
- havola validatsiyasi;
- navbat orqali yuklash;
- foydalanuvchi uchun oddiy limit;
- xatolik va progress xabarlari;
- Docker orqali ishga tushirish;
- asosiy loglar va health-check.

Story, admin panel, ko‘p tillilik va ilg‘or statistika keyingi bosqichda qo‘shiladi. Story funksiyasini alohida tekshirish kerak, chunki story havolalari tez eskiradi va har doim ham ochiq downloader orqali olinmasligi mumkin.

## 8. Keyingi rivojlantirish rejalari

- Web admin panel;
- premium tariflar va to‘lov tizimi;
- yuqori sifatni tanlash: 360p, 720p, original;
- faylni audio formatda alohida yuklab berish;
- bir nechta havolani batch rejimida yuklash;
- kanalga avtomatik joylash;
- S3 yoki boshqa object storage’dan foydalanish;
- monitoring, alert va avtomatik restart;
- proxy qatlamini faqat qonuniy va xavfsiz foydalanish holatlari uchun qo‘shish;
- testlar va downloader adapterlarini alohida modulga ajratish.

## 9. Tavsiyalarim

1. Dastlab barcha Instagram funksiyalarini birdaniga qilish o‘rniga public Reel, video va rasm postlaridan boshlash kerak.
2. Downloader kodini Telegram bot kodidan alohida modul yoki worker sifatida yozish kerak. Shunda Instagram API yoki downloader o‘zgarsa, botning qolgan qismi buzilmaydi.
3. Yuklashlarni navbatga qo‘yish muhim: bitta katta fayl boshqa foydalanuvchilarning so‘rovlarini bloklab qo‘ymasligi kerak.
4. Har bir yuklashga yagona `download_id` berish va statuslarni bazada saqlash diagnostikani osonlashtiradi.
5. Diskka vaqtinchalik fayl yozishdan oldin bo‘sh joy tekshirilishi, yuborilgandan keyin esa fayl o‘chirilishi kerak.
6. Instagram tez-tez o‘zgarishi mumkinligi sababli downloader qatlamiga avtomatik testlar va xatolik monitoringi qo‘shilishi kerak.
7. Bot foydalanuvchiga juda ko‘p texnik xabar bermasligi, xatoliklarni oddiy tilda tushuntirishi kerak.
8. Monetizatsiya rejalashtirilsa, bepul limit, premium tezlik va katta fayl hajmi kabi aniq farqlar oldindan belgilanishi kerak.
9. Production serverda HTTPS, backup, monitoring va avtomatik yangilash jarayoni bo‘lishi kerak.
10. Foydalanuvchi roziligi, maxfiylik siyosati va kontentdan foydalanish qoidalarini loyiha boshidanoq hujjatlashtirish kerak.

## 10. Dastlabki papka tuzilmasi

```text
mediahub/
├── plan.md
├── app/
│   ├── bot/
│   ├── downloader/
│   ├── workers/
│   ├── database/
│   └── config/
├── tests/
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## 11. Tayyorlik mezonlari

- Bot serverda xatosiz ishga tushadi.
- Public Instagram Reel havolasi Telegram orqali qabul qilinadi va media qaytariladi.
- Rasm, video va carousel uchun natija to‘g‘ri yuboriladi.
- Noto‘g‘ri, private yoki mavjud bo‘lmagan havola uchun tushunarli xabar chiqadi.
- Parallel so‘rovlar navbat orqali boshqariladi.
- Vaqtinchalik fayllar tozalanadi.
- Limit, log va xavfsizlik tekshiruvlari ishlaydi.
- Loyihani yangi muhitda README asosida ishga tushirish mumkin.

## 12. Stream orqali yuklash talabi

Asosiy maqsad — media faylni avval to‘liq server diskiga yuklab, keyin Telegram’ga jo‘natmasdan, imkon qadar oqim ko‘rinishida Telegram’ga uzatish.

- Downloader media ma’lumotlarini kichik bufferlar orqali oladi.
- Ma’lumotlar imkon qadar bevosita Telegram upload oqimiga uzatiladi.
- Faylni to‘liq RAM’ga yuklab qo‘yish taqiqlanadi.
- Telegram kutubxonasi yoki downloader streamni qo‘llamasa, vaqtinchalik storage fallback sifatida ishlatiladi.
- Fallback rejimida fayl hajmi, diskdagi bo‘sh joy va avtomatik tozalash nazorat qilinadi.
- Stream uzilib qolsa, vazifa bir necha marta qayta urinadi.
- Har bir oqim uchun read timeout, umumiy timeout va buffer hajmi cheklanadi.

Stream rejimi disk va RAM sarfini kamaytiradi, lekin Telegram Bot API yoki ishlatiladigan kutubxona streamni to‘liq qo‘llamasa, fallback mexanizmi majburiy bo‘ladi.

## 13. 100+ parallel so‘rovdan himoyalanish

100 yoki undan ko‘p foydalanuvchi bir vaqtda havola yuborsa, bot barcha vazifalarni bir vaqtning o‘zida bajarishga urinmasligi kerak.

- Telegram handler faqat so‘rovni qabul qiladi va tezda navbatga qo‘shadi.
- Redis Queue, Celery yoki shunga o‘xshash task queue ishlatiladi.
- Worker’lar soni cheklangan bo‘ladi; dastlab 4–8 ta worker yetarli.
- Har bir worker bir vaqtda faqat bitta og‘ir yuklash bilan ishlaydi.
- Navbat uzunligi uchun maksimal limit o‘rnatiladi.
- Navbat to‘lsa, yangi foydalanuvchiga: `Server band, birozdan keyin qayta urinib ko‘ring` xabari yuboriladi.
- Bitta foydalanuvchi uchun bir vaqtda 1–2 ta faol vazifa limiti o‘rnatiladi.
- Foydalanuvchi va IP bo‘yicha rate limit ishlatiladi.
- Bir xil link takroran yuborilsa, qisqa muddatli cache va `idempotency key` ishlatiladi.
- Har bir vazifa timeout bilan ishlaydi; masalan, 2–5 daqiqadan oshsa bekor qilinadi.
- Worker xatolik bilan to‘xtasa, qolgan vazifalar boshqa worker’lar tomonidan davom ettiriladi.
- Bot, queue va worker’lar alohida servislar sifatida ishlatiladi.
- CPU, RAM, disk, network va navbat uzunligi monitoring qilinadi.
- Backpressure qo‘llanadi: server resurslari xavfli darajaga yetganda yangi vazifalar vaqtincha qabul qilinmaydi.

Tavsiya etiladigan oqim:

```text
Telegram update
      ↓
Tezkor validatsiya + rate limit
      ↓
Redis queue
      ↓
Cheklangan worker pool
      ↓
Stream upload yoki vaqtinchalik storage fallback
      ↓
Telegram foydalanuvchisi
```

## 14. Ehtimoliy xatolar va yechimlar

| Xato yoki holat | Foydalanuvchiga xabar | Tizimdagi chora |
|---|---|---|
| Noto‘g‘ri URL | `Instagram havolasi noto‘g‘ri.` | URL parser va domen validatsiyasi |
| Post o‘chirilgan | `Bu kontent topilmadi yoki o‘chirilgan.` | Vazifani `not_found` statusida yakunlash |
| Private akkaunt | `Private kontentni yuklab bo‘lmaydi.` | Login chetlab o‘tilmaydi, vazifa bekor qilinadi |
| Havola eskirgan | `Havola eskirgan yoki mavjud emas.` | Qayta tekshirish va aniq status qaytarish |
| Instagram rate limit | `Instagram vaqtincha so‘rovlarni chekladi.` | Exponential backoff, retry va global limit |
| Instagram server xatosi | `Instagram vaqtincha javob bermayapti.` | 2–3 marta retry, keyin `failed` status |
| Stream uzilishi | `Yuklash uzilib qoldi, qayta urinilmoqda.` | Chunk retry yoki storage fallback |
| Telegram upload xatosi | `Faylni Telegram’ga yuborib bo‘lmadi.` | Xatoni loglash va nazoratli retry |
| Telegram fayl hajmi limiti | `Fayl juda katta.` | Hajmni oldindan tekshirish yoki ruxsat etilgan siqish |
| Disk to‘lib qolishi | `Server band, keyinroq urinib ko‘ring.` | Streamga o‘tish, cleanup va yangi vazifani vaqtincha to‘xtatish |
| RAM oshib ketishi | `Server vaqtincha band.` | Buffer limit, worker limit va process restart |
| Queue to‘lib qolishi | `Navbat to‘la, birozdan keyin urinib ko‘ring.` | Queue max length va backpressure |
| Worker timeout | `Yuklash juda uzoq davom etdi.` | Vazifani bekor qilish va resurslarni tozalash |
| Bir xil link ko‘p yuborilishi | `Bu havola allaqachon yuklanmoqda.` | Cache va idempotency key |
| Noma’lum media turi | `Bu media turi hozircha qo‘llab-quvvatlanmaydi.` | Media type detection va aniq fallback |
| Buzilgan yoki bo‘sh fayl | `Media faylni olishning imkoni bo‘lmadi.` | MIME, size va fayl yaxlitligini tekshirish |
| Bot qayta ishga tushishi | `Vazifa qayta tiklanmoqda.` | Persistent queue status va recovery |
| Network timeout | `Ulanish sekin yoki uzilgan.` | Connect/read timeout, retry va circuit breaker |
| Shubhali fayl | `Fayl xavfsizlik tekshiruvidan o‘tmadi.` | MIME whitelist, hajm limiti va fayl tekshiruvi |

### Xatoliklarni boshqarish qoidalari

- Har bir vazifa `queued`, `downloading`, `uploading`, `completed`, `failed`, `cancelled` yoki `expired` statuslaridan biriga ega bo‘ladi.
- Foydalanuvchiga texnik traceback yuborilmaydi; texnik ma’lumotlar faqat logga yoziladi.
- Retry faqat vaqtinchalik xatolarda ishlaydi. Noto‘g‘ri URL yoki private kontent uchun qayta-qayta retry qilinmaydi.
- Retry oralig‘i exponential backoff bilan oshiriladi.
- Bitta xato butun botni to‘xtatmasligi uchun exception’lar worker darajasida ushlanadi.
- Har bir vazifa yakunida stream, file handle, temporary file va queue lock yopiladi yoki tozalanadi.
- Takrorlanuvchi xatolar uchun administratorga alert yuboriladi.
