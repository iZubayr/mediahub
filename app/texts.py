import time
from dataclasses import dataclass

import asyncpg


@dataclass(slots=True)
class TextDef:
    key: str
    label: str
    default: str
    help: str
    """Shown to the admin in the editor so they know what placeholders (if
    any) this text supports and where it appears."""


# Every user-facing string the bot sends lives here. Keys are stable across
# deploys; editing a DEFAULT here only changes what's shown to admins who
# have never customized that key — anyone who already edited it via the
# panel keeps their own text (see get_text: DB row always wins over default).
TEXT_DEFS: list[TextDef] = [
    TextDef(
        key="start",
        label="Salomlashuv (/start)",
        default=(
            "Salom! Instagram’dan Reel, video, rasm va carousel yuklash uchun "
            "havolani yuboring.\n\n"
            "Private akkauntlar va login talab qiladigan kontent qo‘llab-quvvatlanmaydi.\n"
            "Yordam: /help"
        ),
        help="Foydalanuvchi /start yuborganda ko‘radigan birinchi xabar.",
    ),
    TextDef(
        key="help",
        label="Yordam (/help)",
        default=(
            "Instagram media havolasini yuboring. Bot public Reel, video, rasm va "
            "carousel’larni qaytaradi.\n\n"
            "Bir daqiqalik limit: {requests_per_minute} ta so‘rov.\n"
            "Kunlik limit: {daily_download_limit} ta yuklash.\n\n"
            "Private, o‘chirilgan yoki mavjud bo‘lmagan kontent yuklanmaydi."
        ),
        help="/help buyrug‘iga javob. {requests_per_minute} va {daily_download_limit} avtomatik almashtiriladi.",
    ),
    TextDef(
        key="invalid_link",
        label="Havola noto‘g‘ri",
        default="Instagram havolasini yuboring.",
        help="Xabarda hech qanday URL topilmaganda ko‘rsatiladi.",
    ),
    TextDef(
        key="invalid_instagram_url",
        label="Instagram havolasi emas",
        default="Havola noto‘g‘ri. Instagram’dagi post, Reel yoki story havolasini yuboring.",
        help="URL topildi, lekin Instagram media havolasi formatiga mos kelmasa.",
    ),
    TextDef(
        key="rate_limited",
        label="Juda tez so‘rov",
        default="So‘rovlar juda tez yuborildi. Bir daqiqadan keyin urinib ko‘ring.",
        help="Daqiqalik so‘rov limitidan oshganda.",
    ),
    TextDef(
        key="daily_limit_reached",
        label="Kunlik limit tugadi",
        default="Bugungi yuklash limitiga yetdingiz.",
        help="Kunlik yuklash limitidan oshganda.",
    ),
    TextDef(
        key="queued",
        label="Navbatga qo‘shildi",
        default="⏳ So‘rov qabul qilindi, navbatga qo‘shilmoqda...",
        help="So‘rov qabul qilingandan keyin, yuklash boshlanmasdan oldin.",
    ),
    TextDef(
        key="too_many_active",
        label="Faol yuklashlar ko‘p",
        default="Sizda faol yuklashlar soni ko‘p. Avvalgi vazifa tugashini kuting.",
        help="Foydalanuvchining faol job limiti to‘lganda.",
    ),
    TextDef(
        key="queue_full",
        label="Navbat to‘la",
        default="Serverdagi navbat hozir to‘la. Birozdan keyin qayta urinib ko‘ring.",
        help="MAX_QUEUE_SIZE ga yetganda.",
    ),
    TextDef(
        key="server_busy",
        label="Server band (umumiy)",
        default="Server vaqtincha band. Birozdan keyin qayta urinib ko‘ring.",
        help="Kutilmagan baza xatosi yuz berganda (rate-limit tekshiruvida).",
    ),
    TextDef(
        key="server_busy_enqueue",
        label="Server band (navbatga qo‘shishda)",
        default="Server vaqtincha band. Keyinroq qayta urinib ko‘ring.",
        help="Kutilmagan baza xatosi yuz berganda (navbatga qo‘shishda).",
    ),
    TextDef(
        key="unexpected_error",
        label="Kutilmagan xato",
        default="So‘rovni qabul qilishda xatolik yuz berdi.",
        help="Yuqoridagilarning hech biriga to‘g‘ri kelmagan xatolarda.",
    ),
    TextDef(
        key="unexpected_download_error",
        label="Kutilmagan yuklash xatosi",
        default="Yuklash vaqtida kutilmagan xatolik yuz berdi. Keyinroq qayta urinib ko‘ring.",
        help="Worker’da media yuklashda tasniflanmagan xato yuz berganda.",
    ),
    TextDef(
        key="checking",
        label="Tekshirilmoqda",
        default="🔎 Instagram kontenti tekshirilmoqda...",
        help="Worker Instagram’dan ma’lumot olishni boshlaganda.",
    ),
    TextDef(
        key="uploading",
        label="Yuklanmoqda",
        default="⬆️ Yuklanmoqda: {index}/{total}",
        help="Har bir media fayl yuborilayotganda. {index} va {total} avtomatik.",
    ),
    TextDef(
        key="done",
        label="Tayyor",
        default="✅ Tayyor. Media fayl(lar) yuborildi.",
        help="Barcha media muvaffaqiyatli yuborilganda.",
    ),
    TextDef(
        key="partial_carousel",
        label="Qisman carousel",
        default=(
            "⚠️ Faqat 1 ta rasm topildi. Agar bu carousel post bo‘lsa, "
            "Instagram qolgan rasmlarni ochiq ko‘rsatmagani uchun ular "
            "yuklanmagan bo‘lishi mumkin."
        ),
        help="Carousel postdan faqat 1 ta rasm olib bo‘lganda.",
    ),
    TextDef(
        key="media_caption",
        label="Media fayl tagyozuvi (caption)",
        default="MediaHub",
        help=(
            "Har bir yuborilgan media fayl ostida chiqadigan matn. "
            "Bir nechta fayl bo‘lsa (carousel) oxiriga « • 1/3 » kabi "
            "raqam avtomatik qo‘shiladi."
        ),
    ),
    TextDef(
        key="force_sub_prompt",
        label="Majburiy obuna talabi",
        default=(
            "Botdan foydalanish uchun quyidagi kanal(lar)ga obuna bo‘ling, "
            "so‘ng «Tekshirish» tugmasini bosing."
        ),
        help="Foydalanuvchi kerakli kanal(lar)ga obuna bo‘lmaganda ko‘rsatiladi.",
    ),
    TextDef(
        key="force_sub_confirmed",
        label="Obuna tasdiqlandi",
        default="✅ Obuna tasdiqlandi. Endi botdan foydalanishingiz mumkin.",
        help="«Tekshirish» tugmasi bosilib, obuna tasdiqlanganda.",
    ),
]

TEXT_DEFS_BY_KEY: dict[str, TextDef] = {item.key: item for item in TEXT_DEFS}

_CACHE_TTL_SECONDS = 15
_cache: dict[str, str] = {}
_cache_expires_at: float = 0.0


async def _refresh_cache(pool: asyncpg.Pool) -> None:
    global _cache, _cache_expires_at
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT text_key, text_value FROM mediahub_texts")
    _cache = {row["text_key"]: row["text_value"] for row in rows}
    _cache_expires_at = time.monotonic() + _CACHE_TTL_SECONDS


async def get_text(pool: asyncpg.Pool, key: str, **format_args: object) -> str:
    """Returns the admin-customized text for `key` if one was saved,
    otherwise the built-in default. Unknown keys return the key itself
    (visibly wrong rather than silently empty, to make mistakes obvious)."""
    if time.monotonic() >= _cache_expires_at:
        await _refresh_cache(pool)
    text_def = TEXT_DEFS_BY_KEY.get(key)
    template = _cache.get(key) or (text_def.default if text_def else key)
    if format_args:
        try:
            return template.format(**format_args)
        except (KeyError, IndexError):
            # A saved custom text with a typo'd placeholder shouldn't crash
            # the bot for every user — fall back to the unformatted text.
            return template
    return template


async def set_text(pool: asyncpg.Pool, key: str, value: str, updated_by: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO mediahub_texts (text_key, text_value, updated_by, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (text_key)
            DO UPDATE SET text_value = $2, updated_by = $3, updated_at = now()
            """,
            key,
            value,
            updated_by,
        )
    global _cache_expires_at
    _cache_expires_at = 0.0  # force refresh on next read


async def reset_text(pool: asyncpg.Pool, key: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM mediahub_texts WHERE text_key = $1", key)
    global _cache_expires_at
    _cache_expires_at = 0.0


async def get_customized_keys(pool: asyncpg.Pool) -> set[str]:
    if time.monotonic() >= _cache_expires_at:
        await _refresh_cache(pool)
    return set(_cache.keys())
