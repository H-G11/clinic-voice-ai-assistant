import tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from core.asr_eval import MicrophoneBenchmark,score,summarize
from core.voice import Transcription


class TestMicrophoneBenchmark(unittest.TestCase):
    def test_wer_cer_and_fields_are_independent(self):
        result=score('Тестов Иван Сергеевич','Тестов Иван','name','тестов иван сергеевич')
        self.assertEqual(1,result['word_errors']);self.assertEqual(3,result['word_count'])
        self.assertGreater(result['char_errors'],0);self.assertFalse(result['field_correct'])
        result=score('Девять тридцать','09:30','time','09:30')
        self.assertTrue(result['field_correct']);self.assertGreater(result['word_errors'],0)

    def test_saved_audio_comparison_is_repeatable_and_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audio=root/'source.wav';audio.write_bytes(b'synthetic test audio')
            bench=MicrophoneBenchmark(root/'bench',source_kind='synthetic_test');session=uuid.uuid4().hex
            self.assertEqual(1,bench.save(audio,'01',session))
            self.assertEqual(1,bench.save(audio,'01',session))
            with patch('core.asr_eval.transcribe_detailed',return_value=Transcription('Запишите меня к хирургу',.1,.2,'cpu',model='small')) as asr:
                report,path=bench.run(session,{'base':{'model_name':'base'},'small':{'model_name':'small'}})
            self.assertEqual(2,asr.call_count)
            self.assertFalse(report['complete']);self.assertEqual(1,report['recordings'])
            self.assertEqual(1,report['summary']['small']['field_correct'])
            self.assertTrue(path.is_relative_to(root));self.assertTrue(audio.exists())

    def test_session_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):MicrophoneBenchmark(tmp).directory('../outside')
