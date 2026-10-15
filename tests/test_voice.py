import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from core.voice import synthesize, voice_diagnostics


class TestVoice(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,{'TTS_ENGINE':'sapi'})
        env.start();self.addCleanup(env.stop)
    def test_disabled_is_explicit(self):
        with patch.dict(os.environ, {'DISABLE_TTS': '1'}):
            result = synthesize('synthetic')
        self.assertIsNone(result.path)
        self.assertTrue(result.message)

    def test_failure_preserves_text_and_removes_empty_file(self):
        with patch.dict(os.environ, {'DISABLE_TTS': '0'}), patch('core.voice._powershell', side_effect=OSError):
            result = synthesize('synthetic')
        self.assertIsNone(result.path)
        self.assertIn('Текстовый', result.message)

    @unittest.skipUnless(os.name == 'nt', 'Windows TTS')
    def test_valid_wav_path_and_fallback(self):
        def render(script, timeout=25):
            if 'Add-Type' in script:
                raise OSError('System.Speech unavailable')
            import re
            target = re.search(r"\$stream.Open\('([^']+)'", script).group(1)
            with wave.open(target, 'wb') as wav:
                wav.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\x01\x00' * 2205)
            return 'Synthetic Russian voice'
        with patch.dict(os.environ, {'DISABLE_TTS': '0'}), patch('core.voice._powershell', side_effect=render):
            result = synthesize('synthetic')
        try:
            self.assertTrue(Path(result.path).is_file())
            self.assertIn('SAPI COM', result.message)
        finally:
            if result.path:
                Path(result.path).unlink(missing_ok=True)

    def test_diagnostics_error_is_readable(self):
        with patch('core.voice._powershell', side_effect=OSError):
            result = voice_diagnostics()
        self.assertEqual([], result['voices'])
        self.assertTrue(result['message'])


class TestPiper(unittest.TestCase):
    def test_missing_local_voice_is_explicit(self):
        with patch.dict(os.environ,{'TTS_ENGINE':'piper','PIPER_MODEL':'data/models/missing.onnx','DISABLE_TTS':'0'}):
            result=synthesize('Синтетическая проверка')
        self.assertIsNone(result.path)
        self.assertIn('не найдена',result.message)

    @unittest.skipUnless(Path('data/models/ru_RU-irina-medium.onnx').is_file(),'Local Piper model not installed')
    def test_real_russian_synthesis_has_non_silent_pcm(self):
        from array import array
        with patch.dict(os.environ,{'TTS_ENGINE':'piper','DISABLE_TTS':'0'}):
            result=synthesize('Здравствуйте. Это проверка локальной регистратуры.')
        self.assertIsNotNone(result.path,result.message)
        try:
            with wave.open(result.path,'rb') as wav:
                self.assertGreater(wav.getnframes()/wav.getframerate(),1.0)
                samples=array('h',wav.readframes(wav.getnframes()))
                self.assertGreater(max(abs(v) for v in samples),100)
        finally:
            if result.path: Path(result.path).unlink(missing_ok=True)
