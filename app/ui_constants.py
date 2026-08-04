"""Small shared module for constants that both bot.py and admin.py need,
to avoid a circular import between them (bot.py imports admin.py for
create_admin_router/is_admin; admin.py needs this button text to route the
reply-keyboard tap)."""

# Exact text of the persistent reply-keyboard "Admin panel" button. When
# tapped, Telegram sends this text as an ordinary message — reply-keyboard
# buttons are not callback buttons, that's a Telegram platform constraint —
# which admin.py's handler matches on to open the panel directly, with no
# "/admin" typing or menu-suggestion tap-then-send step involved.
ADMIN_PANEL_BUTTON_TEXT = "🛠 Admin panel"
