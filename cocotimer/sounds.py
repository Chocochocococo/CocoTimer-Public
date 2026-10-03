"""提醒音：喝水、番茄鐘、行程與任務提醒，各自可以換成自己的音效檔。

自訂的檔案會複製到資料夾裡的 sounds/（跟其他資料放在一起），整個程式資料夾帶走時聲音也會跟著走。
目前只接受 WAV（PCM）：Windows 內建就能播放，不需要額外的解碼元件，程式可以保持輕巧。
"""
import array
import hashlib
import os
import re
import shutil
import sys
import tempfile
import wave
from typing import Optional

from .paths import DATA_DIR, resource_path

SOUND_DIR = "sounds"
KINDS = {
    "water": ("喝水提醒", "water_alert.wav", "sound_water"),
    "pomodoro": ("番茄鐘", "pomodoro_alert.wav", "sound_pomodoro"),
    "reminder": ("行程與任務提醒", "pomodoro_alert.wav", "sound_reminder"),
}


def custom_dir(data_dir: Optional[str] = None) -> str:
    return os.path.join(data_dir or DATA_DIR, SOUND_DIR)


def sound_path(kind: str, custom_name: str = "", data_dir: Optional[str] = None) -> str:
    """實際要播放的檔案：有自訂而且檔案還在就用自訂的，否則用內建音效。"""
    if custom_name:
        path = os.path.join(custom_dir(data_dir), os.path.basename(custom_name))
        if os.path.isfile(path):
            return path
    return resource_path(f"sounds/{KINDS[kind][1]}")


def check_wav(path: str) -> Optional[str]:
    """可以播放就回傳 None，否則回傳原因。"""
    if not path.lower().endswith(".wav"):
        return "目前只支援 WAV 音效檔（.wav）。MP3 可以先用免費的轉檔工具轉成 WAV。"
    try:
        with wave.open(path, "rb") as w:
            if w.getsampwidth() not in (1, 2, 3, 4) or w.getnframes() == 0:
                return "這個 WAV 檔沒有可以播放的聲音。"
            if w.getnframes() / max(1, w.getframerate()) > 30:
                return "提醒音最長 30 秒，請換一個短一點的檔案。"
    except (wave.Error, EOFError, OSError) as e:
        return f"這個檔案不是一般的 WAV 格式，無法播放（{e}）。"
    return None


def import_sound(kind: str, source: str, data_dir: Optional[str] = None) -> str:
    """把使用者選的檔案複製到資料夾，回傳存在設定裡的檔名。"""
    folder = custom_dir(data_dir)
    os.makedirs(folder, exist_ok=True)
    stem = re.sub(r'[\\/:*?"<>|]+', "_", os.path.splitext(os.path.basename(source))[0]).strip() or "sound"
    name = f"{kind}_{stem}.wav"
    target = os.path.join(folder, name)
    if os.path.abspath(source) != os.path.abspath(target):
        shutil.copyfile(source, target)
    return name


def remove_unused(used_names, data_dir: Optional[str] = None) -> None:
    """刪掉沒有再被任何提醒使用的自訂音效檔。"""
    folder = custom_dir(data_dir)
    if not os.path.isdir(folder):
        return
    keep = {os.path.basename(n) for n in used_names if n}
    for name in os.listdir(folder):
        if name.lower().endswith(".wav") and name not in keep:
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass


# --- 調整音量（Windows 內建的播放功能沒有音量設定，所以先做一份調好音量的檔案） ---

def scale_wav(source: str, target: str, volume: float) -> bool:
    """把 WAV 的音量乘上 volume（0～1）存成 target。支援 8／16／32 位元 PCM；其他格式回傳 False（照原音量播放）。"""
    volume = max(0.0, min(1.0, volume))
    with wave.open(source, "rb") as w:
        params = w.getparams()
        frames = w.readframes(w.getnframes())
    width = params.sampwidth
    if width == 1:  # 8 位元是無號數，中心值 128
        data = bytes(int(128 + (b - 128) * volume) for b in frames)
    elif width in (2, 4):
        samples = array.array("h" if width == 2 else "i")
        samples.frombytes(frames)
        if sys.byteorder == "big":
            samples.byteswap()
        for i, v in enumerate(samples):
            samples[i] = int(v * volume)
        if sys.byteorder == "big":
            samples.byteswap()
        data = samples.tobytes()
    else:
        return False
    with wave.open(target, "wb") as out:
        out.setparams(params)
        out.writeframes(data)
    return True


def volume_adjusted(source: str, volume: float) -> str:
    """回傳調好音量的暫存檔（同一個檔案、同一個音量只做一次）；音量 100% 或無法調整時回傳原檔。"""
    if volume >= 0.995:
        return source
    try:
        stat = os.stat(source)
    except OSError:
        return source
    key = hashlib.sha1(f"{os.path.abspath(source)}|{stat.st_mtime}|{stat.st_size}".encode()).hexdigest()[:12]
    folder = os.path.join(tempfile.gettempdir(), "cocotimer-sounds")
    target = os.path.join(folder, f"{key}_{int(round(volume * 100))}.wav")
    if os.path.isfile(target):
        return target
    try:
        os.makedirs(folder, exist_ok=True)
        return target if scale_wav(source, target, volume) else source
    except (OSError, wave.Error, EOFError):
        return source
