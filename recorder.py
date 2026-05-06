import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

from config import config
from platform_utils import PLATFORM
from utils import resolve_filename, unique_path

logger = logging.getLogger(__name__)

CHUNK_FRAMES = 512
QUEUE_MAXSIZE = 200
GAIN = 0.707  # -3 dB per channel to prevent clipping


class RecorderState:
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"


class Recorder:
    def __init__(self, on_state_change: Optional[Callable[[str], None]] = None):
        self._state = RecorderState.IDLE
        self._on_state_change = on_state_change

        self._mic_queue: queue.Queue = queue.Queue(maxsize=QUEUE_MAXSIZE)
        self._loopback_queue: queue.Queue = queue.Queue(maxsize=QUEUE_MAXSIZE)

        self._mixer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._paused = False

        # PyAudio handles (Windows)
        self._pa = None
        self._mic_stream = None
        self._loopback_stream = None

        # sounddevice handles (macOS / Linux)
        self._sd_mic_stream = None
        self._sd_loopback_stream = None

        self._sf_writer: Optional[sf.SoundFile] = None

        self._current_wav_path: Optional[Path] = None
        self._start_time: Optional[float] = None
        self._part_index = 0
        self._base_stem: Optional[str] = None

        self._target_rate: int = 48000
        self._channels: int = 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def elapsed_seconds(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.monotonic() - self._start_time

    def start_recording(self) -> bool:
        if self._state != RecorderState.IDLE:
            return False

        self._target_rate = config.get("sample_rate", 48000)
        self._channels = config.get("channels", 1)

        try:
            if PLATFORM == "Windows":
                self._open_streams_windows()
            else:
                self._open_streams_sounddevice()
        except Exception as e:
            logger.error("Failed to open audio streams: %s", e)
            self._cleanup_streams()
            return False

        stem = resolve_filename()
        self._base_stem = stem
        self._part_index = 1
        wav_path = self._new_wav_path(stem, part=None)
        self._current_wav_path = wav_path

        try:
            self._sf_writer = sf.SoundFile(
                str(wav_path),
                mode="w",
                samplerate=self._target_rate,
                channels=self._channels,
                subtype="PCM_16",
            )
        except OSError as e:
            logger.error("Cannot open output file %s: %s", wav_path, e)
            self._cleanup_streams()
            return False

        config.set("recording_in_progress", True)
        config.set("recording_temp_path", str(wav_path))
        config.save()

        self._stop_event.clear()
        self._paused = False
        self._start_time = time.monotonic()

        self._mixer_thread = threading.Thread(
            target=self._mixer_loop, daemon=True, name="mixer"
        )
        self._mixer_thread.start()

        self._set_state(RecorderState.RECORDING)
        logger.info("Recording started → %s", wav_path)
        return True

    def stop_recording(self) -> Optional[Path]:
        if self._state == RecorderState.IDLE:
            return None

        self._stop_event.set()
        self._paused = False

        if self._mixer_thread and self._mixer_thread.is_alive():
            self._mixer_thread.join(timeout=5)

        self._cleanup_streams()
        wav_path = self._current_wav_path
        self._current_wav_path = None
        self._start_time = None

        config.set("recording_in_progress", False)
        config.set("recording_temp_path", "")
        config.save()

        self._set_state(RecorderState.IDLE)
        logger.info("Recording stopped, WAV saved: %s", wav_path)
        return wav_path

    def pause(self):
        if self._state != RecorderState.RECORDING:
            return
        self._paused = True
        self._set_state(RecorderState.PAUSED)
        logger.info("Recording paused")

    def resume(self):
        if self._state != RecorderState.PAUSED:
            return
        self._paused = False
        self._set_state(RecorderState.RECORDING)
        logger.info("Recording resumed")

    # ------------------------------------------------------------------
    # Windows stream (pyaudiowpatch / WASAPI loopback)
    # ------------------------------------------------------------------

    def _open_streams_windows(self):
        import pyaudiowpatch as pyaudio

        self._pa = pyaudio.PyAudio()
        mic_device_cfg = config.get("mic_device", "default")
        loopback_device_cfg = config.get("speaker_device", "default")

        # --- Mic stream ---
        # Discover the native channel count so we don't force mono on a
        # device that only supports stereo — downmix happens in the callback.
        mic_idx, mic_native_ch, mic_native_rate = self._query_input_device_windows(
            mic_device_cfg
        )

        def mic_cb(in_data, frame_count, time_info, status):
            try:
                buf = np.frombuffer(in_data, dtype=np.int16).copy()
                if mic_native_ch > 1 and self._channels == 1:
                    buf = buf.reshape(-1, mic_native_ch).mean(axis=1).astype(np.int16)
                if mic_native_rate != self._target_rate:
                    buf = self._resample(buf, mic_native_rate, self._target_rate)
                if not self._mic_queue.full():
                    self._mic_queue.put_nowait(buf)
            except Exception as e:
                logger.warning("Mic callback error: %s", e)
            return (None, pyaudio.paContinue)

        mic_kwargs = dict(
            format=pyaudio.paInt16,
            channels=mic_native_ch,
            rate=mic_native_rate,
            input=True,
            frames_per_buffer=CHUNK_FRAMES,
            stream_callback=mic_cb,
        )
        if mic_idx is not None:
            mic_kwargs["input_device_index"] = mic_idx

        self._mic_stream = self._pa.open(**mic_kwargs)
        self._mic_stream.start_stream()
        logger.info(
            "Mic stream opened (device=%s, rate=%d, ch=%d)",
            mic_device_cfg, mic_native_rate, mic_native_ch,
        )

        # --- Loopback stream ---
        loopback_device = self._find_loopback_device_windows(loopback_device_cfg)
        if loopback_device is None:
            logger.warning("No WASAPI loopback device found — recording mic only")
        else:
            loopback_rate = int(loopback_device["defaultSampleRate"])
            loopback_ch = min(int(loopback_device.get("maxInputChannels", 2)), 2)

            def loopback_cb(in_data, frame_count, time_info, status):
                try:
                    buf = np.frombuffer(in_data, dtype=np.int16).copy()
                    if loopback_ch > 1 and self._channels == 1:
                        buf = buf.reshape(-1, loopback_ch).mean(axis=1).astype(np.int16)
                    if loopback_rate != self._target_rate:
                        buf = self._resample(buf, loopback_rate, self._target_rate)
                    if not self._loopback_queue.full():
                        self._loopback_queue.put_nowait(buf)
                except Exception as e:
                    logger.warning("Loopback callback error: %s", e)
                return (None, pyaudio.paContinue)

            self._loopback_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=loopback_ch,
                rate=loopback_rate,
                input=True,
                input_device_index=loopback_device["index"],
                frames_per_buffer=CHUNK_FRAMES,
                stream_callback=loopback_cb,
            )
            self._loopback_stream.start_stream()
            logger.info(
                "Loopback stream opened (device=%s, rate=%d, ch=%d)",
                loopback_device["name"], loopback_rate, loopback_ch,
            )

    def _query_input_device_windows(self, device_cfg: str):
        """Return (device_index, native_channels, native_rate) for an input device."""
        import pyaudiowpatch as pyaudio

        if device_cfg == "default":
            try:
                wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
                idx = wasapi.get("defaultInputDevice")
                if idx is not None:
                    info = self._pa.get_device_info_by_index(idx)
                    return (
                        idx,
                        int(info.get("maxInputChannels", 1)),
                        int(info["defaultSampleRate"]),
                    )
            except Exception:
                pass
            return None, 1, self._target_rate

        count = self._pa.get_device_count()
        for i in range(count):
            info = self._pa.get_device_info_by_index(i)
            if info["name"] == device_cfg and info["maxInputChannels"] > 0:
                return (
                    i,
                    int(info["maxInputChannels"]),
                    int(info["defaultSampleRate"]),
                )

        logger.warning("Mic device '%s' not found, using default", device_cfg)
        return None, 1, self._target_rate

    def _find_loopback_device_windows(self, speaker_cfg: str):
        import pyaudiowpatch as pyaudio

        try:
            wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            logger.error("WASAPI host API not available")
            return None

        if speaker_cfg == "default":
            default_out_idx = wasapi_info.get("defaultOutputDevice")
            if default_out_idx is None:
                return None
            target_name = self._pa.get_device_info_by_index(default_out_idx)["name"]
        else:
            target_name = speaker_cfg

        # First pass: match by name
        for lb in self._pa.get_loopback_device_info_generator():
            if target_name.lower() in lb["name"].lower():
                return lb

        # Fallback: first available loopback
        for lb in self._pa.get_loopback_device_info_generator():
            logger.warning("Using fallback loopback device: %s", lb["name"])
            return lb

        return None

    # ------------------------------------------------------------------
    # macOS / Linux stream (sounddevice)
    # ------------------------------------------------------------------

    def _open_streams_sounddevice(self):
        import sounddevice as sd
        from platform_utils import find_loopback_device_sounddevice

        mic_device_cfg = config.get("mic_device", "default")
        loopback_device_cfg = config.get("speaker_device", "default")

        mic_device = None if mic_device_cfg == "default" else mic_device_cfg

        def mic_callback(indata, frames, time_info, status):
            try:
                mono = indata[:, 0] if indata.shape[1] > 1 else indata.ravel()
                buf = (mono * 32767).astype(np.int16)
                if not self._mic_queue.full():
                    self._mic_queue.put_nowait(buf)
            except Exception as e:
                logger.warning("Mic callback error: %s", e)

        self._sd_mic_stream = sd.InputStream(
            device=mic_device,
            samplerate=self._target_rate,
            channels=1,
            dtype="float32",
            blocksize=CHUNK_FRAMES,
            callback=mic_callback,
        )
        self._sd_mic_stream.start()
        logger.info("Mic stream opened (sounddevice, device=%s)", mic_device_cfg)

        # --- Loopback ---
        if loopback_device_cfg == "default":
            loopback_name = find_loopback_device_sounddevice()
        else:
            loopback_name = loopback_device_cfg

        if loopback_name is None:
            logger.warning(
                "No loopback device found. "
                "On macOS install BlackHole (https://existential.audio/blackhole/); "
                "on Linux ensure PulseAudio monitor sources are available."
            )
        else:
            def loopback_callback(indata, frames, time_info, status):
                try:
                    mono = indata[:, 0] if indata.shape[1] > 1 else indata.ravel()
                    buf = (mono * 32767).astype(np.int16)
                    if not self._loopback_queue.full():
                        self._loopback_queue.put_nowait(buf)
                except Exception as e:
                    logger.warning("Loopback callback error: %s", e)

            try:
                self._sd_loopback_stream = sd.InputStream(
                    device=loopback_name,
                    samplerate=self._target_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=CHUNK_FRAMES,
                    callback=loopback_callback,
                )
                self._sd_loopback_stream.start()
                logger.info("Loopback stream opened (sounddevice, device=%s)", loopback_name)
            except Exception as e:
                logger.warning("Could not open loopback device '%s': %s — mic only", loopback_name, e)
                self._sd_loopback_stream = None

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup_streams(self):
        # PyAudio streams (Windows)
        for stream in (self._mic_stream, self._loopback_stream):
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
        self._mic_stream = None
        self._loopback_stream = None

        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

        # sounddevice streams (macOS/Linux)
        for stream in (self._sd_mic_stream, self._sd_loopback_stream):
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
        self._sd_mic_stream = None
        self._sd_loopback_stream = None

        if self._sf_writer is not None:
            try:
                self._sf_writer.close()
            except Exception:
                pass
            self._sf_writer = None

        for q in (self._mic_queue, self._loopback_queue):
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    # ------------------------------------------------------------------
    # Mixer loop — real-time paced to fix the "few seconds" bug
    # ------------------------------------------------------------------
    #
    # Root cause: the old code used queue.get(timeout=0.5) for EACH queue.
    # When the loopback queue was empty (no audio playing on the output
    # device), every iteration blocked for ~1 second but only wrote
    # 512/48000 ≈ 10ms of audio, making the file grow 94× slower than
    # real-time. Fix: get_nowait() + sleep for the remainder of the
    # chunk duration so the file always grows at real-time speed.

    def _mixer_loop(self):
        max_seconds = config.get("max_recording_hours", 4) * 3600
        silence = np.zeros(CHUNK_FRAMES, dtype=np.int16)
        chunk_duration = CHUNK_FRAMES / self._target_rate  # ~10.67ms at 48 kHz

        try:
            while not self._stop_event.is_set():
                loop_start = time.monotonic()

                if self.elapsed_seconds >= max_seconds:
                    logger.info("Max recording length reached, splitting file")
                    self._split_file()

                # Non-blocking reads; substitute silence when a stream has
                # no data (e.g. loopback device quiet between call segments)
                try:
                    mic_buf = self._mic_queue.get_nowait()
                except queue.Empty:
                    mic_buf = silence.copy()

                try:
                    lb_buf = self._loopback_queue.get_nowait()
                except queue.Empty:
                    lb_buf = silence.copy()

                # Align lengths (resampling may produce ±1 sample)
                min_len = min(len(mic_buf), len(lb_buf))
                mic_f = mic_buf[:min_len].astype(np.float32) / 32768.0 * GAIN
                lb_f = lb_buf[:min_len].astype(np.float32) / 32768.0 * GAIN
                out = (np.clip(mic_f + lb_f, -1.0, 1.0) * 32767).astype(np.int16)

                if not self._paused and self._sf_writer is not None:
                    if self._channels == 1:
                        self._sf_writer.write(out)
                    else:
                        self._sf_writer.write(out.reshape(-1, self._channels))

                # Sleep for the remainder of this chunk period so the file
                # grows at real-time speed even when streams are silent.
                elapsed = time.monotonic() - loop_start
                remaining = chunk_duration - elapsed
                if remaining > 0:
                    time.sleep(remaining)

        except Exception as e:
            logger.error("Mixer loop crashed: %s", e, exc_info=True)
            self._stop_event.set()

    # ------------------------------------------------------------------
    # File management
    # ------------------------------------------------------------------

    def _split_file(self):
        if self._sf_writer:
            self._sf_writer.close()
        self._part_index += 1
        wav_path = self._new_wav_path(self._base_stem, part=self._part_index)
        self._current_wav_path = wav_path
        config.set("recording_temp_path", str(wav_path))
        config.save()
        self._sf_writer = sf.SoundFile(
            str(wav_path),
            mode="w",
            samplerate=self._target_rate,
            channels=self._channels,
            subtype="PCM_16",
        )
        self._start_time = time.monotonic()
        logger.info("Split to new file: %s", wav_path)

    def _new_wav_path(self, stem: str, part: Optional[int]) -> Path:
        folder = config.get(
            "output_folder",
            str(Path.home() / "Documents" / "Teams Recordings"),
        )
        if part is not None:
            stem = f"{stem} (part_{part})"
        return unique_path(folder, stem, ".wav")

    # ------------------------------------------------------------------
    # Resampling
    # ------------------------------------------------------------------

    @staticmethod
    def _resample(buf: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        try:
            import samplerate
            ratio = to_rate / from_rate
            floats = buf.astype(np.float32) / 32768.0
            resampled = samplerate.resample(floats, ratio, converter_type="sinc_fastest")
            return (resampled * 32767).astype(np.int16)
        except ImportError:
            old_len = len(buf)
            new_len = int(round(old_len * to_rate / from_rate))
            x_old = np.linspace(0, 1, old_len)
            x_new = np.linspace(0, 1, new_len)
            return np.interp(x_new, x_old, buf.astype(np.float32)).astype(np.int16)

    # ------------------------------------------------------------------

    def _set_state(self, new_state: str):
        self._state = new_state
        if self._on_state_change:
            self._on_state_change(new_state)


def convert_to_mp3(
    wav_path: Path,
    on_done: Optional[Callable[[Optional[Path]], None]] = None,
):
    import threading

    def _convert():
        try:
            from pydub import AudioSegment

            bitrate = f"{config.get('mp3_bitrate', 128)}k"
            audio = AudioSegment.from_wav(str(wav_path))
            mp3_path = wav_path.with_suffix(".mp3")
            audio.export(str(mp3_path), format="mp3", bitrate=bitrate)
            logger.info("MP3 export complete: %s", mp3_path)
            try:
                wav_path.unlink()
            except OSError:
                pass
            if on_done:
                on_done(mp3_path)
        except Exception as e:
            logger.error("MP3 conversion failed: %s", e)
            if on_done:
                on_done(None)

    t = threading.Thread(target=_convert, daemon=True, name="mp3-convert")
    t.start()
    return t
