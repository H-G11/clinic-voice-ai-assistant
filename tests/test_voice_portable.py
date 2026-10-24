"""Piper engine selection and caching must not depend on the host OS."""

import os
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core import voice


class PortableVoice(unittest.TestCase):
    def test_piper_runs_and_reloads_when_model_path_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / 'a.onnx', root / 'b.onnx'
            first.touch()
            second.touch()

            def render(text, stream):
                stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                stream.writeframes(b'\x01\x00' * 160)

            engine = Mock()
            engine.synthesize_wav.side_effect = render
            factory = Mock()
            factory.load.return_value = engine
            with patch.object(voice, '_piper_voice', None), patch.object(voice, '_piper_model_path', None), patch.dict('sys.modules', {'piper': SimpleNamespace(PiperVoice=factory)}), patch.dict(os.environ, {'TTS_ENGINE': 'piper', 'DISABLE_TTS': '0'}):
                for model in (first, first, second):
                    with patch.dict(os.environ, {'PIPER_MODEL': str(model)}):
                        result = voice.synthesize('Синтетическая проверка')
                    self.assertIsNotNone(result.path, result.message)
                    try:
                        with wave.open(result.path) as wav:
                            self.assertEqual(160, wav.getnframes())
                    finally:
                        Path(result.path).unlink(missing_ok=True)
            self.assertEqual(2, factory.load.call_count)

    def test_unknown_engine_is_explicit(self):
        with patch.dict(os.environ, {'TTS_ENGINE': 'unknown', 'DISABLE_TTS': '0'}):
            result = voice.synthesize('synthetic')
        self.assertIsNone(result.path)
        self.assertIn('TTS_ENGINE', result.message)
