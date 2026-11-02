"""User-facing words in English and Turkish."""

# Sentences spoken by the offline recipes are written in English and wrapped
# in _(); the Turkish session fills TRANSLATIONS["tr"] (English text -> Turkish).
TRANSLATIONS = {"tr": {}}
_language = "en"


def set_language(lang):
    global _language
    _language = lang


def _(text):
    return TRANSLATIONS.get(_language, {}).get(text, text)

MESSAGES = {
    "en": {
        "warming": "One moment...",
        "listening": "Listening...",
        "heard_nothing": "I didn't catch that. Press the shortcut and try again.",
        "stopping": "Okay, I stopped.",
        "nudge": "Take your time. Press the shortcut and say \"do it\" if you want me to.",
        "too_many_steps": "I stopped here because this was taking too many steps.",
        "api_error": "I can't reach the AI service right now. Check the internet connection and the API key.",
        "no_key": "I need an OpenAI API key first. Open my settings from the icon in the panel.",
        "no_shell": "My pointer helper isn't running. Log out and back in once, then try again.",
        "error": "Something went wrong, so I stopped.",
        "unknown_offline": "I don't know that one without the internet yet. Try: open the calculator, change the wallpaper, or make a folder.",
        "menu_talk": "Talk to Clicky",
        "menu_type": "Type a request...",
        "menu_stop": "Stop",
        "menu_settings": "Settings",
        "menu_quit": "Quit",
        "ask_title": "What should I show you?",
        "ask_hint": "For example: show me how to change the wallpaper",
        "settings_title": "Clicky settings",
        "settings_online": "Use the internet for things I don't know",
        "settings_key": "OpenAI API key",
        "settings_language": "Language",
        "settings_speak": "Speak answers out loud",
        "settings_performer": "Who clicks",
        "performer_assistant": "Clicky does it, I watch",
        "performer_user": "I click, Clicky points",
        "settings_shortcut": "Shortcut",
        "save": "Save",
        "key_saved": "Key saved",
    },
    "tr": {
        "warming": "Bir saniye...",
        "listening": "Dinliyorum...",
        "heard_nothing": "Anlayamadım. Kısayola basıp tekrar dener misin?",
        "stopping": "Tamam, durdum.",
        "nudge": "Acele etme. İstersen kısayola basıp \"sen yap\" de, ben yapayım.",
        "too_many_steps": "Bu iş çok fazla adım sürdüğü için burada durdum.",
        "api_error": "Yapay zekâ hizmetine şu an ulaşamıyorum. İnternet bağlantısını ve API anahtarını kontrol et.",
        "no_key": "Önce bir OpenAI API anahtarı gerekiyor. Paneldeki simgeden ayarlarımı aç.",
        "no_shell": "İşaretçi yardımcım çalışmıyor. Bir kez oturumu kapatıp yeniden aç, sonra tekrar dene.",
        "error": "Bir şeyler ters gitti, bu yüzden durdum.",
        "unknown_offline": "Bunu internet olmadan henüz bilmiyorum. Şunları deneyebilirsin: hesap makinesini aç, arka planı değiştir ya da klasör oluştur.",
        "menu_talk": "Clicky ile konuş",
        "menu_type": "İsteğini yaz...",
        "menu_stop": "Durdur",
        "menu_settings": "Ayarlar",
        "menu_quit": "Çık",
        "ask_title": "Sana ne göstereyim?",
        "ask_hint": "Örneğin: masaüstü arka planını nasıl değiştiririm",
        "settings_title": "Clicky ayarları",
        "settings_online": "Bilmediğim işler için interneti kullan",
        "settings_key": "OpenAI API anahtarı",
        "settings_language": "Dil",
        "settings_speak": "Cevapları sesli söyle",
        "settings_performer": "Kim tıklasın",
        "performer_assistant": "Clicky yapsın, ben izleyeyim",
        "performer_user": "Ben tıklayayım, Clicky göstersin",
        "settings_shortcut": "Kısayol",
        "save": "Kaydet",
        "key_saved": "Anahtar kaydedildi",
    },
}

# Short spoken replies while Clicky waits for the user to do a step.
INTERJECTIONS = {
    "en": {
        "stop": ["stop", "cancel", "never mind", "nevermind", "quit", "enough"],
        "do_it": ["do it", "you do it", "do it for me", "you do", "go ahead", "show me", "you click"],
        "next": ["done", "next", "i did it", "did it", "ok", "okay", "finished", "continue", "ready"],
    },
    "tr": {
        "stop": ["dur", "durdur", "iptal", "vazgeç", "yeter", "kapat"],
        "do_it": ["sen yap", "yap", "benim yerime yap", "sen tıkla", "göster"],
        "next": ["tamam", "yaptım", "oldu", "devam", "sonraki", "bitti", "hazır"],
    },
}


YES_NO = {
    "en": {"yes": ["yes", "yeah", "yep", "sure", "ok", "okay", "go ahead", "do it", "confirm", "please do", "of course"],
           "no": ["no", "nope", "don't", "do not", "cancel", "stop", "never mind", "nevermind", "wait"]},
    "tr": {"yes": ["evet", "tamam", "olur", "yap", "devam", "tabii"],
           "no": ["hayır", "yok", "iptal", "dur", "vazgeç", "yapma"]},
}


def classify_yes_no(reply, lang):
    """True, False or None for a spoken answer to a yes/no question. 'No' wins over 'yes'."""
    if not reply:
        return None
    phrase = " " + " ".join("".join(ch if ch.isalnum() or ch.isspace() or ch == "'" else " " for ch in reply.lower()).split()) + " "
    table = YES_NO.get(lang, YES_NO["en"])
    if any(f" {w} " in phrase for w in table["no"]):
        return False
    if any(f" {w} " in phrase for w in table["yes"]):
        return True
    return None


def text(config, key):
    lang = config.get("language", "en")
    return MESSAGES.get(lang, MESSAGES["en"]).get(key) or MESSAGES["en"][key]


def classify(reply, lang):
    """'stop', 'do_it', 'next' or None for a short spoken reply."""
    if not reply:
        return None
    words = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in reply.lower()).split()
    if not words or len(words) > 6:
        return None
    phrase = f" {' '.join(words)} "
    table = INTERJECTIONS.get(lang, INTERJECTIONS["en"])
    for verdict in ("stop", "do_it", "next"):
        if any(f" {p} " in phrase for p in table[verdict]):
            return verdict
    return None
