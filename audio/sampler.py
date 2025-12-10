import os
import math
import json
import threading

import numpy as np
import sounddevice as sd
import soundfile as sf


# ============================================================
# SAMPLE OBJECT
# ============================================================

class Sample:
    """
    Représente un sample mono/stéréo + paramètres individuels.
    """
    def __init__(self, data: np.ndarray, sr: int):
        if data.ndim == 1:
            data = data[:, np.newaxis]
        self.data = data.astype(np.float32)
        self.sr = int(sr)

        self.num_frames = self.data.shape[0]
        self.channels = self.data.shape[1]

        # ---- PARAMETRES PAR SAMPLE ----
        self.volume = 1.0

        # Attack & release individuels (en secondes)
        self.attack_seconds = 0.002
        self.release_seconds = 0.080

        # Trimming par sample en pourcentage
        self.trim_start = 0.0
        self.trim_end = 1.0


# ============================================================
# VOICE OBJECT
# ============================================================

class Voice:
    """
    Une instance de sample en train de jouer.
    """
    def __init__(self, sampler, sample: Sample, note: int, velocity: int):
        self.sampler = sampler
        self.sample = sample
        self.note = int(note)

        self.velocity = max(0, min(127, velocity))
        self.position = 0.0
        self.done = False

        # Raccourcis locaux
        self.sr = sampler.sample_rate
        self.trim_start_frame = int(sample.trim_start * sample.num_frames)
        self.trim_end_frame = int(sample.trim_end * sample.num_frames)
        self.trim_length = max(1, self.trim_end_frame - self.trim_start_frame)

        self.attack_samples = max(1, int(sample.attack_seconds * self.sr))
        self.release_samples = max(1, int(sample.release_seconds * self.sr))


    def mix_into(self, out_buffer: np.ndarray):
        """Mélange cette voix dans le buffer de sortie."""
        if self.done:
            return

        frames, out_channels = out_buffer.shape

        start = self.trim_start_frame + int(self.position)
        end = start + frames
        if start >= self.trim_end_frame:
            self.done = True
            return

        max_end = min(end, self.trim_end_frame)
        length = max_end - start
        if length <= 0:
            self.done = True
            return

        segment = self.sample.data[start:max_end]

        # gestion des canaux
        if self.sample.channels < out_channels:
            segment = np.repeat(segment, out_channels, axis=1)
        elif self.sample.channels > out_channels:
            segment = segment[:, :out_channels]

        # indices réels du sample (pour enveloppes)
        idx = np.arange(start, max_end, dtype=np.float32)

        # Attack
        attack_env = np.clip((idx - self.trim_start_frame) / self.attack_samples, 0.0, 1.0)

        # Release
        dist_to_end = (self.trim_end_frame - idx).astype(np.float32)
        release_env = np.clip(dist_to_end / self.release_samples, 0.0, 1.0)

        env = np.minimum(attack_env, release_env)

        base_gain = (self.velocity / 127.0) * self.sample.volume * self.sampler.global_volume
        env = (env * base_gain).astype(np.float32)
        env = env[:, np.newaxis]

        out_buffer[:length] += segment[:length] * env

        self.position += length
        if self.position >= self.trim_length:
            self.done = True


# ============================================================
# SAMPLER
# ============================================================

class Sampler:
    """
    Sampler polyphonique complet avec :
    - Volume global
    - Attack/Release individuels
    - Trim Start / End individuels
    - Volume par sample
    - JSON auto
    """

    def __init__(self,
                 sample_rate: int = 44100,
                 block_size: int = 512,
                 max_voices: int = 64):

        self.sample_rate = int(sample_rate)
        self.block_size = int(block_size)
        self.max_voices = int(max_voices)

        self.samples = {}           # note -> Sample
        self.voices = []            # voix actives

        self.global_volume = 1.0    # volume global
        self.output_channels = 2

        self.lock = threading.Lock()

        # Création du stream audio
        try:
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                channels=self.output_channels,
                dtype="float32",
                callback=self._callback
            )
            self.stream.start()
            print("[SAMPLER] Stream audio démarré.")
        except Exception as e:
            print("[SAMPLER] ERREUR ouverture stream :", e)
            self.stream = None


    # ---------------------------------------------------------
    # JSON CONFIG
    # ---------------------------------------------------------

    def _default_config(self):
        return {
            "global": {
                "volume": 1.0
            },
            "samples": {}
        }

    def _load_json_config(self, folder_path):
        config_path = os.path.join(folder_path, "volume.json")

        if os.path.isfile(config_path):
            try:
                with open(config_path, "r", encoding="utf8") as f:
                    cfg = json.load(f)
                print("[SAMPLER] volume.json chargé.")
                return cfg
            except:
                pass

        # Si absent → créer un fichier minimal
        cfg = self._default_config()
        try:
            with open(config_path, "w", encoding="utf8") as f:
                json.dump(cfg, f, indent=2)
        except:
            pass

        print("[SAMPLER] volume.json créé automatiquement.")
        return cfg


    def save_json_config(self, folder_path):
        config_path = os.path.join(folder_path, "volume.json")
        with self.lock:
            cfg = {
                "global": {
                    "volume": self.global_volume
                },
                "samples": {}
            }
            for note, s in self.samples.items():
                cfg["samples"][str(note)] = {
                    "volume": s.volume,
                    "attack_seconds": s.attack_seconds,
                    "release_seconds": s.release_seconds,
                    "trim_start": s.trim_start,
                    "trim_end": s.trim_end
                }

        try:
            with open(config_path, "w", encoding="utf8") as f:
                json.dump(cfg, f, indent=2)
            print("[SAMPLER] volume.json sauvegardé.")
        except Exception as e:
            print("[SAMPLER] ERREUR sauvegarde JSON :", e)


    # ---------------------------------------------------------
    # CHARGEMENT DES SAMPLES
    # ---------------------------------------------------------

    def _resample(self, data, sr):
        if sr == self.sample_rate:
            return data.astype(np.float32)

        if data.ndim == 1:
            data = data[:, np.newaxis]

        frames = data.shape[0]
        duration = frames / sr

        new_frames = int(duration * self.sample_rate)

        t_old = np.linspace(0, duration, frames, endpoint=False)
        t_new = np.linspace(0, duration, new_frames, endpoint=False)

        resampled = np.zeros((new_frames, data.shape[1]), dtype=np.float32)
        for c in range(data.shape[1]):
            resampled[:, c] = np.interp(t_new, t_old, data[:, c])

        return resampled


    def load_folder(self, folder_path):
        cfg = self._load_json_config(folder_path)

        with self.lock:
            self.samples.clear()

        for fname in os.listdir(folder_path):
            if not fname.lower().endswith(".wav"):
                continue

            stem = os.path.splitext(fname)[0]
            try:
                note = int(stem)
            except:
                print("[SAMPLER] Ignoré :", fname)
                continue

            path = os.path.join(folder_path, fname)
            try:
                data, sr = sf.read(path, dtype="float32")
            except:
                print("[SAMPLER] Erreur lecture :", fname)
                continue

            data = self._resample(data, sr)
            sample = Sample(data, self.sample_rate)

            # Charger paramètres depuis JSON
            scfg = cfg["samples"].get(str(note), {})
            sample.volume = float(scfg.get("volume", 1.0))
            sample.attack_seconds = float(scfg.get("attack_seconds", 0.002))
            sample.release_seconds = float(scfg.get("release_seconds", 0.080))
            sample.trim_start = float(scfg.get("trim_start", 0.0))
            sample.trim_end = float(scfg.get("trim_end", 1.0))

            with self.lock:
                self.samples[note] = sample

        print("[SAMPLER]", len(self.samples), "samples chargés.")


    # ---------------------------------------------------------
    # PLAY NOTE
    # ---------------------------------------------------------

    def play(self, note, velocity=127):
        if self.stream is None:
            return

        with self.lock:
            if note not in self.samples:
                return

            v = Voice(self, self.samples[note], note, velocity)

            if len(self.voices) >= self.max_voices:
                self.voices.pop(0)

            self.voices.append(v)


    # ---------------------------------------------------------
    # PARAMETRES PAR SAMPLE
    # ---------------------------------------------------------

    def set_sample_volume(self, note, value):
        with self.lock:
            if note in self.samples:
                self.samples[note].volume = float(value)

    def set_sample_attack(self, note, seconds):
        with self.lock:
            if note in self.samples:
                self.samples[note].attack_seconds = max(0.0, float(seconds))

    def set_sample_release(self, note, seconds):
        with self.lock:
            if note in self.samples:
                self.samples[note].release_seconds = max(0.0, float(seconds))

    def set_sample_trim_start(self, note, value):
        with self.lock:
            if note in self.samples:
                s = self.samples[note]
                v = float(value)
                s.trim_start = max(0.0, min(v, s.trim_end - 0.01))

    def set_sample_trim_end(self, note, value):
        with self.lock:
            if note in self.samples:
                s = self.samples[note]
                v = float(value)
                s.trim_end = max(s.trim_start + 0.01, min(v, 1.0))


    # ---------------------------------------------------------
    # AUDIO CALLBACK
    # ---------------------------------------------------------

    def _callback(self, outdata, frames, time_info, status):
        out = np.zeros((frames, self.output_channels), dtype=np.float32)

        with self.lock:
            active = list(self.voices)

        for v in active:
            v.mix_into(out)

        with self.lock:
            self.voices = [vv for vv in self.voices if not vv.done]

        np.clip(out, -1.0, 1.0, out=out)
        outdata[:] = out


    # ---------------------------------------------------------
    # CLOSE
    # ---------------------------------------------------------

    def close(self):
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except:
                pass

        with self.lock:
            self.voices.clear()
