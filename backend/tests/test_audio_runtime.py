"""Check native audio wheels without downloading a speech model."""
import io
import unittest
import wave

import numpy as np

from queme.services.audio_analysis import _load_audio


class AudioRuntimeTests(unittest.TestCase):
    def test_installed_audio_runtime_decodes_a_recording(self):
        # Imports deliberately fail if native runtime libraries cannot load.
        import av
        import librosa
        import soundfile
        from faster_whisper import WhisperModel

        samples = (np.sin(2 * np.pi * 220 * np.arange(16000) / 16000) * 12000)
        recording = io.BytesIO()
        with wave.open(recording, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(samples.astype("<i2").tobytes())

        # Require the PyAV path to succeed, rather than hiding failure via fallback.
        from unittest.mock import patch
        with patch("librosa.load", side_effect=AssertionError("PyAV decoding failed")):
            decoded, rate = _load_audio(recording.getvalue())
        self.assertIsNotNone(decoded)
        self.assertEqual(rate, 16000)
        self.assertEqual(len(decoded), 16000)
        self.assertGreater(float(np.max(np.abs(decoded))), 0.1)
