import os
import math
import json
import threading

import numpy as np
import sounddevice as sd
import soundfile as sf


class Sample:
    """
    Représente un sample en RAM.
    data : np.ndarray float32, shape (n_frames, n_channels)
    sr   : sample rate
    """
    def __init__(self, data: np.ndarray, sr: int):
        # Toujours 2D : (frames, channels)
        if data.ndim == 1:
            data = data[:, np.newaxis]
        self.data = data.astype(np.float32)
        self.sr = int(sr)
        self.num_frames = self.data.shape[0]
        self.channels = self.data.shape[1]


class Voice:
    """
    Une voix active (une note en cours de lecture).
    - sample : Sample
    - sampler : référence au Sampler (pour lire global_volume, sample_volumes...)
    - note : numéro MIDI
    - position : index flottant dans le sample
    - velocity : 0–127
    - attack_samples / release_samples : enveloppe simple
    """
    def __init__(self, sampler, sample: Sample, note: int, velocity: int,
                 attack_samples: int, release_samples: int):
        self.sampler = sampler
        self.sample = sample
        self.note = int(note)
        self.position = 0.0  # en frames
        self.velocity = max(0, min(127, int(velocity)))
        self.attack_samples = max(1, attack_samples)
        self.release_samples = max(1, release_samples)
        self.done = False

    def mix_into(self, out_buffer: np.ndarray):
        """
        Mélange cette voix dans out_buffer (shape: frames x channels).
        Met self.done = True si la voix est terminée.
        """
        if self.done:
            return

        frames, out_channels = out_buffer.shape
        start_pos = int(self.position)
        end_pos = start_pos + frames

        # Lorsque la voix a dépassé la fin du sample
        if start_pos >= self.sample.num_frames:
            self.done = True
            return

        # Limiter à la taille réelle du sample
        max_pos = min(end_pos, self.sample.num_frames)
        length = max_pos - start_pos
        if length <= 0:
            self.done = True
            return

        # Extraire la portion de sample
        segment = self.sample.data[start_pos:max_pos]  # (length, channels)

        # Gestion du nombre de canaux : on adapte au buffer de sortie
        if self.sample.channels < out_channels:
            # Du mono vers stéréo (ou plus) : duplication
            segment = np.repeat(segment, out_channels, axis=1)
        elif self.sample.channels > out_channels:
            # On tronque si le sample a plus de canaux
            segment = segment[:, :out_channels]

        # Construction de l'enveloppe Attack/Release
        idx = np.arange(start_pos, max_pos, dtype=np.float32)

        # Attack : montée de 0 à 1 sur attack_samples
        attack_env = np.clip(idx / float(self.attack_samples), 0.0, 1.0)

        # Release : descente sur release_samples à la fin du sample
        dist_to_end = (self.sample.num_frames - idx).astype(np.float32)
        release_env = np.clip(dist_to_end / float(self.release_samples), 0.0, 1.0)

        env = np.minimum(attack_env, release_env)

        # Récupérer les paramètres actuels du sampler
        # (global_volume et volume par sample peuvent changer à chaud)
        with self.sampler.lock:
            global_volume = self.sampler.global_volume
            sample_volume = self.sampler.sample_volumes.get(self.note, 1.0)

        # Gain de base à partir de la vélocité
        base_gain = self.velocity / 127.0

        # Gain final : env * velocity * volumes
        gain = (env * base_gain * sample_volume * global_volume).astype(np.float32)
        gain = gain[:, np.newaxis]  # (length, 1) pour broadcast

        segment = segment[:length] * gain

        # Mélange dans le buffer de sortie
        out_buffer[:length] += segment

        # Avancer la position
        self.position += float(length)

        # Si on a atteint ou dépassé la fin du sample, marquer comme terminé
        if self.position >= self.sample.num_frames:
            self.done = True


class Sampler:
    """
    Sampler polyphonique "pro" pour Pysha :
    - Charge un dossier de WAV (nommés par numéro de note : 36.wav, 60.wav, etc.)
    - Utilise en option un fichier volume.json pour :
        * attack_ms / release_ms globaux
        * volume global
        * volume par sample
    - Polyphonie multiple
    - Enveloppe Attack/Release simple
    - API :
        load_folder(path)
        play(note, velocity)
        set_global_attack(ms)
        set_global_release(ms)
        set_global_volume(vol)
        set_sample_volume(note, vol)
        get_sample_volume(note)
        save_json_config(folder_path)
    """

    def __init__(self,
                 sample_rate: int = 44100,
                 block_size: int = 512,
                 max_voices: int = 64):
        self.sample_rate = int(sample_rate)
        self.block_size = int(block_size)
        self.max_voices = int(max_voices)

        self.samples = {}         # note_number -> Sample
        self.sample_volumes = {}  # note_number -> volume
        self.voices = []          # liste de Voice actives

        self.lock = threading.Lock()

        # Paramètres globaux (peuvent être modifiés à chaud)
        self.default_attack_ms = 2.0
        self.default_release_ms = 80.0
        self.global_volume = 1.0  # 0.0–? (1.0 conseillé)

        # On fixe le nombre de canaux à 2 (stéréo) pour la sortie
        self.output_channels = 2

        # Stream audio principal
        try:
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                channels=self.output_channels,
                dtype='float32',
                callback=self._audio_callback
            )
            self.stream.start()
            print(f"[SAMPLER] Stream audio démarré @ {self.sample_rate} Hz, {self.output_channels} canaux.")
        except Exception as e:
            print(f"[SAMPLER] Impossible d'ouvrir le stream audio : {e}")
            self.stream = None

    # -------------------------------------------------------------
    # CHARGEMENT DES SAMPLES + CONFIG JSON
    # -------------------------------------------------------------
    def _resample_if_needed(self, data: np.ndarray, sr: int) -> np.ndarray:
        """
        Resample le buffer vers self.sample_rate si nécessaire.
        Utilise np.interp pour rester léger (suffisant pour un sampler).
        """
        if sr == self.sample_rate:
            return data.astype(np.float32)

        if data.ndim == 1:
            data = data[:, np.newaxis]

        num_frames, channels = data.shape
        duration = num_frames / float(sr)

        # Nouveau nombre de frames
        new_num_frames = int(math.ceil(duration * self.sample_rate))

        # Axes temporels
        t_old = np.linspace(0.0, duration, num=num_frames, endpoint=False, dtype=np.float32)
        t_new = np.linspace(0.0, duration, num=new_num_frames, endpoint=False, dtype=np.float32)

        resampled = np.zeros((new_num_frames, channels), dtype=np.float32)
        for ch in range(channels):
            resampled[:, ch] = np.interp(t_new, t_old, data[:, ch].astype(np.float32))

        return resampled

    def _default_config(self):
        """
        Crée une config par défaut en mémoire.
        """
        return {
            "global": {
                "attack_ms": self.default_attack_ms,
                "release_ms": self.default_release_ms,
                "volume": self.global_volume
            },
            "samples": {}
        }

    def _load_json_config(self, folder_path: str):
        """
        Charge volume.json si présent, sinon le crée avec des valeurs par défaut.

        Format :
        {
          "global": {
            "attack_ms": 5.0,
            "release_ms": 120.0,
            "volume": 1.0
          },
          "samples": {
            "36": { "volume": 0.8 },
            "37": { "volume": 0.5 }
          }
        }
        """
        config_path = os.path.join(folder_path, "volume.json")

        cfg = None
        if os.path.isfile(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                print(f"[SAMPLER] Config JSON chargée : {config_path}")
            except Exception as e:
                print(f"[SAMPLER] Erreur lecture volume.json : {e}")
                cfg = None

        if cfg is None:
            # Créer une config par défaut et l'écrire
            cfg = self._default_config()
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
                print(f"[SAMPLER] volume.json créé avec valeurs par défaut : {config_path}")
            except Exception as e:
                print(f"[SAMPLER] Erreur création volume.json : {e}")

        global_cfg = cfg.get("global", {}) or {}
        samples_cfg = cfg.get("samples", {}) or {}

        # Appliquer les valeurs globales
        with self.lock:
            self.default_attack_ms = float(global_cfg.get("attack_ms", self.default_attack_ms))
            self.default_release_ms = float(global_cfg.get("release_ms", self.default_release_ms))
            self.global_volume = float(global_cfg.get("volume", self.global_volume))

        return samples_cfg

    def load_folder(self, folder_path: str):
        """
        Charge tous les WAV d'un dossier, dont le nom de fichier est un numéro MIDI.
        Exemple :
            36.wav -> note 36
            60.wav -> note 60

        Et lit volume.json (créé si absent) pour :
            - attack_ms / release_ms globaux
            - volume global
            - volume par sample
        """
        if not os.path.isdir(folder_path):
            print(f"[SAMPLER] Dossier introuvable : {folder_path}")
            return

        # D'abord : charger (ou créer) la config JSON
        samples_cfg = self._load_json_config(folder_path)

        count = 0
        with self.lock:
            self.samples.clear()
            self.sample_volumes.clear()

        for filename in os.listdir(folder_path):
            if not filename.lower().endswith(".wav"):
                continue

            name_no_ext = os.path.splitext(filename)[0]
            try:
                note = int(name_no_ext)
            except ValueError:
                print(f"[SAMPLER] Ignoré (nom non numérique) : {filename}")
                continue

            fullpath = os.path.join(folder_path, filename)
            try:
                data, sr = sf.read(fullpath, dtype='float32')
            except Exception as e:
                print(f"[SAMPLER] Erreur lecture {filename} : {e}")
                continue

            # Resample si besoin
            data = self._resample_if_needed(np.array(data), sr)
            sample = Sample(data, self.sample_rate)

            # Volume par sample depuis le JSON (sinon 1.0)
            sample_cfg = samples_cfg.get(str(note), {}) or {}
            vol = float(sample_cfg.get("volume", 1.0))

            with self.lock:
                self.samples[note] = sample
                self.sample_volumes[note] = vol

            count += 1

        print(f"[SAMPLER] {count} samples chargés depuis {folder_path}")

    # -------------------------------------------------------------
    # LECTURE DES NOTES
    # -------------------------------------------------------------
    def play(self, note: int, velocity: int = 127,
             attack_ms: float | None = None,
             release_ms: float | None = None):
        """
        Joue une note :
        - note : numéro MIDI
        - velocity : 0–127
        - attack_ms / release_ms : si None → utilise les valeurs globales
        """
        if self.stream is None:
            # Aucune sortie audio dispo
            return

        with self.lock:
            sample = self.samples.get(int(note))

        if sample is None:
            # Aucun sample pour cette note → silence
            return

        # Si pas de valeurs explicites, on utilise les valeurs globales
        with self.lock:
            if attack_ms is None:
                attack_ms = self.default_attack_ms
            if release_ms is None:
                release_ms = self.default_release_ms

        attack_samples = int(self.sample_rate * (float(attack_ms) / 1000.0))
        release_samples = int(self.sample_rate * (float(release_ms) / 1000.0))

        voice = Voice(self, sample, note, velocity, attack_samples, release_samples)

        with self.lock:
            if len(self.voices) >= self.max_voices:
                # On supprime la plus ancienne pour faire de la place
                self.voices.pop(0)
            self.voices.append(voice)

    # -------------------------------------------------------------
    # CALLBACK AUDIO
    # -------------------------------------------------------------
    def _audio_callback(self, outdata, frames, time_info, status):
        """
        Callback SoundDevice : remplit le buffer outdata.
        """
        # Buffer de sortie initialisé à zéro
        out_buffer = np.zeros((frames, self.output_channels), dtype=np.float32)

        with self.lock:
            active_voices = list(self.voices)

        for voice in active_voices:
            voice.mix_into(out_buffer)

        # Après mix, on nettoie les voix terminées
        with self.lock:
            self.voices = [v for v in self.voices if not v.done]

        # Clamp léger pour éviter les saturations
        np.clip(out_buffer, -1.0, 1.0, out=out_buffer)

        outdata[:] = out_buffer

    # -------------------------------------------------------------
    # API POUR CONTRÔLE (Push / midi_cc_mode)
    # -------------------------------------------------------------
    def set_global_attack(self, ms: float):
        """
        Change l'attack globale (en ms). Affectera les prochaines notes jouées.
        """
        with self.lock:
            self.default_attack_ms = max(0.0, float(ms))

    def set_global_release(self, ms: float):
        """
        Change le release global (en ms). Affectera les prochaines notes jouées.
        """
        with self.lock:
            self.default_release_ms = max(0.0, float(ms))

    def set_global_volume(self, vol: float):
        """
        Change le volume global du sampler.
        vol typiquement entre 0.0 et 1.0 (mais pas obligé).
        """
        with self.lock:
            self.global_volume = max(0.0, float(vol))

    def set_sample_volume(self, note: int, vol: float):
        """
        Change le volume d'un sample spécifique.
        """
        note = int(note)
        with self.lock:
            if note in self.samples:
                self.sample_volumes[note] = max(0.0, float(vol))

    def get_sample_volume(self, note: int) -> float:
        """
        Retourne le volume du sample (ou 1.0 si non défini).
        """
        note = int(note)
        with self.lock:
            return float(self.sample_volumes.get(note, 1.0))

    def save_json_config(self, folder_path: str):
        """
        Sauvegarde volume.json dans folder_path avec :
        - attack_ms / release_ms / volume globaux actuels
        - volume par sample (pour tous les samples chargés)
        """
        config_path = os.path.join(folder_path, "volume.json")

        with self.lock:
            cfg = {
                "global": {
                    "attack_ms": float(self.default_attack_ms),
                    "release_ms": float(self.default_release_ms),
                    "volume": float(self.global_volume)
                },
                "samples": {
                    str(note): {"volume": float(vol)}
                    for note, vol in self.sample_volumes.items()
                }
            }

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            print(f"[SAMPLER] volume.json sauvegardé : {config_path}")
        except Exception as e:
            print(f"[SAMPLER] Erreur sauvegarde volume.json : {e}")

    # -------------------------------------------------------------
    # ARRÊT / CLEANUP
    # -------------------------------------------------------------
    def close(self):
        """
        Arrête le stream audio proprement.
        À appeler si besoin lors de la fermeture de l'app.
        """
        try:
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
        except Exception:
            pass
        self.stream = None
        with self.lock:
            self.voices.clear()
