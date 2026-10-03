import os
import wave

from cocotimer import sounds


def make_wav(path, seconds=0.2, rate=8000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))


def test_check_wav(tmp_path):
    good = tmp_path / "叮.wav"
    make_wav(good)
    assert sounds.check_wav(str(good)) is None
    long = tmp_path / "long.wav"
    make_wav(long, seconds=31)
    assert "30 秒" in sounds.check_wav(str(long))
    fake = tmp_path / "fake.wav"
    fake.write_bytes(b"not a wav")
    assert "不是一般的 WAV" in sounds.check_wav(str(fake))
    assert "WAV" in sounds.check_wav(str(tmp_path / "song.mp3"))


def test_import_path_and_cleanup(tmp_path):
    data = tmp_path / "data"
    src = tmp_path / "我的:提醒.wav"
    make_wav(src)
    name = sounds.import_sound("water", str(src), str(data))
    assert name == "water_我的_提醒.wav"
    assert sounds.sound_path("water", name, str(data)) == os.path.join(str(data), "sounds", name)
    # 自訂檔不見了，或沒有自訂時用內建音效
    assert sounds.sound_path("water", "", str(data)).endswith("water_alert.wav")
    assert sounds.sound_path("reminder", "missing.wav", str(data)).endswith("pomodoro_alert.wav")
    sounds.remove_unused([], str(data))
    assert not os.listdir(os.path.join(str(data), "sounds"))


def test_volume_scaling(tmp_path):
    src = tmp_path / "loud.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        import array
        w.writeframes(array.array("h", [10000, -20000, 30000]).tobytes())
    out = tmp_path / "quiet.wav"
    assert sounds.scale_wav(str(src), str(out), 0.5)
    with wave.open(str(out), "rb") as w:
        import array
        a = array.array("h")
        a.frombytes(w.readframes(3))
    assert list(a) == [5000, -10000, 15000]
    assert sounds.volume_adjusted(str(src), 1.0) == str(src)
    cached = sounds.volume_adjusted(str(src), 0.3)
    assert cached != str(src) and cached == sounds.volume_adjusted(str(src), 0.3)
