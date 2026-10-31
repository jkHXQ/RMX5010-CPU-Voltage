#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 jkHXQ
"""Actual saved-sample replay plus synthetic rejection cases; no hardware access."""
from pathlib import Path
import argparse
import json
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--awk', default='awk')
    args = ap.parse_args()
    a = (ROOT / 'tests/fixtures/sample1.txt').read_text(encoding='utf-8')
    b = (ROOT / 'tests/fixtures/sample2.txt').read_text(encoding='utf-8')
    row = next(x for x in b.splitlines() if x.startswith('ROW '))
    cases = [
        ('saved_actual_samples', a, b, True),
        ('missing_row_synthetic', a, b.replace(row + '\n', '', 1), False),
        ('duplicate_row_synthetic', a, b.replace(row + '\n', row + '\n' + row + '\n', 1), False),
        ('wrong_protocol_synthetic', a, b.replace('VERSION=0x40000', 'VERSION=0x30000'), False),
        ('wrong_query_count_synthetic', a, b.replace('wire_queries=38', 'wire_queries=37'), False),
        ('wrong_return_code_synthetic', a, b.replace('rc=-22', 'rc=-5'), False),
        ('replayed_sample_synthetic', a, a, False),
        ('wrong_current_state_synthetic', a, b.replace('CURRENT_LEVEL 0 ', 'CURRENT_LEVEL 1 '), False),
    ]
    result = []
    with tempfile.TemporaryDirectory(prefix='voltage-v2-parser-') as d:
        d = Path(d)
        for name, first, second, should_pass in cases:
            p1, p2, jout = d / 's1.txt', d / 's2.txt', d / (name + '.json')
            p1.write_bytes(first.encode('utf-8')); p2.write_bytes(second.encode('utf-8'))
            p = subprocess.run([args.awk, '-v', 'json=' + str(jout), '-f', str(ROOT / 'src/mt/decode_score.awk'),
                                str(ROOT / 'src/mt/reference_author.txt'), str(p1), str(p2)],
                               capture_output=True)
            report = p.stdout.decode('utf-8', 'replace')
            assert (p.returncode == 0) == should_pass, (name, p.returncode, report)
            if should_pass:
                value = json.loads(jout.read_text(encoding='utf-8'))
                assert (value['score_cluster0'], value['score_cluster1'], value['score']) == (3217, 1856, 2536)
                assert value['current_level_query_rc'] == [-22, -22]
                assert len(value['rows']) == 32
                assert report.count('当前等级不可用') == 2
            else:
                assert 'VALIDATION=FAILED' in report
                assert not jout.exists()
            result.append({'name': name, 'expected_accept': should_pass, 'returncode': p.returncode, 'pass': True})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
