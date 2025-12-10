import os
import threading
import math

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
    - position : index flottant dans le sample
    - velocity : 0–127
    - attack_samples / release_samples : enveloppe simple
    """
    def __init__(self, sample: Sample, velocity: int,
                 attack_samples: int, release_samples: int):
        self.sample = sample
        self.position = 0.0  # en frames
        self.velocity = max(0, min(127, int(velocity)))
        self.attack_samples = max(1, attack_samples)
        self.release_samples = max(1, release_samples)
        self.done = False

        # Gain max basé sur la vélocité
        self.base_gain = self.velocity / 127.0

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

        # Gain final (env * vélocité)
        gain = (env * self.base_gain).astype(np.float32)
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
    - Polyphonie multiple
    - Enveloppe Attack/Release simple
    - Compatible avec l'interface existante : load_folder(), play(note, velocity)
    """

    def __init__(self,
                 sample_rate: int = 44100,
                 block_size: int = 512,
                 max_voices: int = 64):
        self.sample_rate = int(sample_rate)
        self.block_size = int(block_size)
        self.max_voices = int(max_voices)

        self.samples = {}   # note_number -> Sample
        self.voices = []    # liste de Voice actives
        self.lock = threading.Lock()

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
    # CHARGEMENT DES SAMPLES
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

    def load_folder(self, folder_path: str):
        """
        Charge tous les WAV d'un dossier, dont le nom de fichier est un numéro MIDI.
        Exemple :
            36.wav -> note 36
            60.wav -> note 60
        """

        if not os.path.isdir(folder_path):
            print(f"[SAMPLER] Dossier introuvable : {folder_path}")
            return

        count = 0
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

            self.samples[note] = sample
            count += 1

        print(f"[SAMPLER] {count} samples chargés depuis {folder_path}")

    # -------------------------------------------------------------
    # LECTURE DES NOTES
    # -------------------------------------------------------------
    def play(self, note: int, velocity: int = 127,
             attack_ms: float = 2.0,
             release_ms: float = 80.0):
        """
        Joue une note :
        - note : numéro MIDI
        - velocity : 0–127
        - attack_ms / release_ms : enveloppe simple (fade in / fade out)
        """
        if self.stream is None:
            # Aucune sortie audio dispo
            return

        sample = self.samples.get(int(note))
        if sample is None:
            # Aucun sample pour cette note → silence
            return

        attack_samples = int(self.sample_rate * (attack_ms / 1000.0))
        release_samples = int(self.sample_rate * (release_ms / 1000.0))

        voice = Voice(sample, velocity, attack_samples, release_samples)

        with self.lock:
            if len(self.voices) >= self.max_voices:
                # On supprime la plus ancienne (ou la première) pour faire de la place
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
            # On fait une copie de la liste pour éviter les problèmes
            # en cas de suppression de voix durant l'itération
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
