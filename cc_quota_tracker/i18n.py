"""語系：語系檔在 languages/ 底下，正體中文與英文各一份；這裡負責解析要用哪一份，以及取出文案。

文案只在畫面層（視窗、命令列）套用，看板與核心不帶文案。語系鍵一律寫成完整的字串字面值——直接寫在 `text(lang, "age.minutes", n=5)`
裡，或放在表格、三元式裡再傳給 text——不要用字串組出來：測試掃原始碼裡長得像語系鍵的字面值，查出用到但沒定義、
與定義了但沒人用的鍵。供應商給的原始值（鎖定原因、限額名稱）不翻譯。"""
import locale
import os
import sys
from typing import Optional

from .languages import en, zh_tw

ZH_TW, EN = "zh-TW", "en"
SUPPORTED = (ZH_TW, EN)
FALLBACK = EN  # 系統語系不在支援清單時用英文
_CATALOGS = {ZH_TW: zh_tw.STRINGS, EN: en.STRINGS}
_TRADITIONAL_REGIONS = {"tw", "hk", "mo"}


def language_of(tag: Optional[str]) -> Optional[str]:
    """語系標籤（zh-TW、zh_TW.UTF-8、zh-Hant-TW、en_US…）對應到支援的語系；不支援就是 None。
    正體中文以字體判定：Windows 的 zh-TW、zh-HK、zh-MO 與明寫 Hant 的標籤都讀正體；簡體與沒寫地區的 zh 不算。"""
    if not tag:
        return None
    parts = tag.split(".")[0].replace("_", "-").lower().split("-")
    if parts[0] == "en":
        return EN
    if parts[0] == "zh" and ("hant" in parts or _TRADITIONAL_REGIONS & set(parts[1:])):
        return ZH_TW
    return None


def resolve(preference: str, system_tag: Optional[str]) -> str:
    """設定檔的 language（system／zh-TW／en）換算成實際使用的語系。system_tag 是作業系統的語系標籤。"""
    if preference in SUPPORTED:
        return preference
    return language_of(system_tag) or FALLBACK


def system_tag() -> Optional[str]:
    """作業系統的介面語系標籤，例如 zh-TW；讀不到就是 None。"""
    if sys.platform == "win32":
        import ctypes
        try:
            kernel32 = ctypes.windll.kernel32
            buffer = ctypes.create_unicode_buffer(85)  # LOCALE_NAME_MAX_LENGTH
            # 介面語言以 LANGID 給出；LCIDToLocaleName 把它換成標籤
            if kernel32.LCIDToLocaleName(kernel32.GetUserDefaultUILanguage(), buffer, len(buffer), 0):
                return buffer.value
        except (AttributeError, OSError):
            pass  # 讀不到就當作系統語系未知：每輪 poll 都會問，不能因此讓視窗出錯
        return None
    return os.environ.get("LC_ALL") or os.environ.get("LANG") or locale.getlocale()[0]


def text(lang: str, key: str, **params) -> str:
    return _CATALOGS[lang][key].format(**params)
