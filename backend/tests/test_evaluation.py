import importlib.util
from pathlib import Path
import json
import asyncio


def test_frozen_offline_report_is_reproducible():
    path = Path(__file__).resolve().parents[2] / 'scripts/evaluate.py'
    spec = importlib.util.spec_from_file_location('offline_evaluation', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    expected = json.loads((path.parents[1] / 'eval/reports/offline.json').read_text(encoding='utf-8'))
    assert asyncio.run(module.evaluate()) == expected
