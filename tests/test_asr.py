import os
import sys
import unittest
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core import voice


class TestASR(unittest.TestCase):
    def tearDown(self):
        voice._model = None
        voice._model_key=None

    def test_quiet_edges_are_not_trimmed_and_silence_is_not_transcribed(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'quiet.wav'
            samples=(np.sin(np.arange(32000)*2*np.pi*440/16000)*100).astype('<i2')
            with wave.open(str(path),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(samples.tobytes())
            audio,info,_=voice.prepare_audio(str(path))
            self.assertEqual(32000,len(audio));self.assertGreater(info['peak'],0)
            with wave.open(str(path),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(bytes(32000))
            model=Mock()
            with patch('faster_whisper.WhisperModel',return_value=model):result=voice.transcribe_detailed(str(path),device='cpu')
            self.assertEqual('',result.text);self.assertTrue(result.needs_review)
            model.transcribe.assert_not_called()

    def test_low_logprob_requires_review(self):
        model=Mock();model.transcribe.return_value=(iter([SimpleNamespace(text='Да',avg_logprob=-1.8,no_speech_prob=.1)]),None)
        with patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=Mock(return_value=model))}):
            value=voice.transcribe_detailed('synthetic.wav',device='cpu')
        self.assertTrue(value.needs_review)
        self.assertEqual(-1.8,value.confidence['avg_logprob'])

    def test_stereo_48k_is_resampled_without_cutting_edges(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'stereo.wav'
            tone=(np.sin(np.arange(48000)*2*np.pi*440/48000)*8000).astype('<i2')
            with wave.open(str(path),'wb') as wav:
                wav.setnchannels(2);wav.setsampwidth(2);wav.setframerate(48000)
                wav.writeframes(np.column_stack((tone,tone)).tobytes())
            audio,info,_=voice.prepare_audio(str(path))
        self.assertEqual((48000,2),(info['source_rate'],info['source_channels']))
        self.assertEqual(1,audio.ndim)
        self.assertAlmostEqual(1,len(audio)/16000,places=2)
        self.assertTrue(info['near_start']);self.assertTrue(info['near_end'])

    def test_switching_model_reloads_the_model(self):
        class Model:
            def transcribe(self,*args,**kwargs):return iter([SimpleNamespace(text='test')]),None
        constructor=Mock(side_effect=[Model(),Model()])
        with patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=constructor)}),patch.dict(os.environ,{'ASR_DEVICE':'cpu'}):
            a=voice.transcribe_detailed('synthetic.wav',model_name='base')
            b=voice.transcribe_detailed('synthetic.wav',model_name='small')
        self.assertEqual(2,constructor.call_count)
        self.assertEqual(('base','small'),(a.model,b.model))

    def test_vad_is_configurable_and_no_implicit_audio_trim(self):
        model=Mock();model.transcribe.return_value=(iter([SimpleNamespace(text='Да')]),None)
        with patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=Mock(return_value=model))}):
            value=voice.transcribe_detailed('synthetic.wav',vad_filter=False,beam_size=5)
        self.assertFalse(model.transcribe.call_args.kwargs['vad_filter'])
        self.assertNotIn('clip_timestamps',model.transcribe.call_args.kwargs)
        self.assertEqual(5,value.beam_size)

    def test_lazy_model_and_separate_latency(self):
        model = Mock()
        model.transcribe.return_value = (iter([SimpleNamespace(text=' девять тридцать ')]), None)
        constructor = Mock(return_value=model)
        with patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(WhisperModel=constructor)}), patch.dict(os.environ, {'ASR_DEVICE': 'cpu', 'ASR_LOCAL_ONLY': '1', 'ASR_BEAM_SIZE': '2', 'ASR_MODEL': 'base'}):
            result = voice.transcribe_detailed('synthetic.wav')
        self.assertEqual('девять тридцать', result.text)
        self.assertGreaterEqual(result.asr_seconds, 0)
        self.assertGreaterEqual(result.load_seconds, 0)
        constructor.assert_called_once_with('base', device='cpu', compute_type='int8', local_files_only=True)
        self.assertEqual(2, model.transcribe.call_args.kwargs['beam_size'])

    def test_cuda_failure_uses_only_cached_cpu_model(self):
        class Model:
            def transcribe(self, *args, **kwargs):
                return iter([SimpleNamespace(text='synthetic')]), None
        constructor = Mock(side_effect=[RuntimeError('CUDA unavailable'), Model()])
        with patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(WhisperModel=constructor)}), patch.dict(os.environ, {'ASR_DEVICE': 'cuda', 'ASR_BEAM_SIZE': '1'}):
            result = voice.transcribe_detailed('synthetic.wav')
        self.assertEqual('cpu', result.device)
        self.assertTrue(result.warning)
        self.assertTrue(constructor.call_args.kwargs['local_files_only'])

    def test_bad_decoding_configuration_does_not_load_model(self):
        constructor = Mock()
        with patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(WhisperModel=constructor)}), patch.dict(os.environ, {'ASR_BEAM_SIZE': '100'}):
            with self.assertRaises(RuntimeError):
                voice.transcribe_detailed('synthetic.wav')
        constructor.assert_not_called()
