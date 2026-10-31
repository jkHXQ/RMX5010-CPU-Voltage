#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 jkHXQ
"""Verify the shipped v2 bytes and embedded payload without executing them."""
from pathlib import Path
import base64
import hashlib
import io
import json
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    m = json.loads((ROOT / 'abi/release-v2.json').read_text(encoding='utf-8'))
    for path, expected in m['source_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
    script = ROOT / 'dist/SM8750_CPU体质测试_MT直接执行_v2.sh'
    header, encoded = script.read_bytes().split(b'__CPU_VOLTAGE_PAYLOAD_BASE64__\n', 1)
    blob = base64.b64decode(encoded)
    assert hashlib.sha256(blob).hexdigest() == m['payload_sha256']
    assert m['payload_sha256'].encode() in header
    expected_names = {'run_core.sh', 'decode_score.awk', 'reference_author.txt', 'live_voltage_scmi_v1.ko'}
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tf:
        assert len(tf.getmembers()) == 4
        assert {x.name for x in tf.getmembers()} == expected_names
        for member in tf.getmembers():
            assert member.isfile()
            source = ROOT / ('prebuilt' if member.name.endswith('.ko') else 'src/mt') / member.name
            assert tf.extractfile(member).read() == source.read_bytes(), member.name
    with zipfile.ZipFile(ROOT / 'dist/SM8750_CPU体质测试_MT单文件版_v2.zip') as z:
        assert set(z.namelist()) == {script.name, '使用说明.md'}
        assert z.read(script.name) == script.read_bytes()
    profile = json.loads((ROOT / 'abi/profile-v2.json').read_text(encoding='utf-8'))
    assert profile['source_sha256'] == m['source_sha256']['src/kernel/cpu_voltage_probe.c']
    assert profile['ko_sha256'] == m['source_sha256']['prebuilt/live_voltage_scmi_v1.ko']
    print('PASS: source/KO/release hashes, embedded payload, ZIP and ABI metadata agree.')


if __name__ == '__main__':
    main()
