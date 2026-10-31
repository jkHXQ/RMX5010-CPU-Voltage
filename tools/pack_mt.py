#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 jkHXQ
"""Repack the verified v2 payload; never modify dist/ or load a kernel module."""
from pathlib import Path
import argparse
import base64
import gzip
import hashlib
import io
import json
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=ROOT / 'build/SM8750_CPU体质测试_MT直接执行_v2.sh')
    args = ap.parse_args()
    if args.output.exists():
        ap.error('output already exists; choose a new path')
    meta = json.loads((ROOT / 'abi/release-v2.json').read_text(encoding='utf-8'))
    payload_io = io.BytesIO()
    with gzip.GzipFile(fileobj=payload_io, mode='wb', filename='', compresslevel=9,
                       mtime=meta['gzip_mtime']) as gz:
        with tarfile.open(fileobj=gz, mode='w') as tf:
            for name in ('run_core.sh', 'decode_score.awk', 'reference_author.txt', 'live_voltage_scmi_v1.ko'):
                p = ROOT / ('prebuilt' if name.endswith('.ko') else 'src/mt') / name
                data = p.read_bytes()
                expected = meta['source_sha256'][p.relative_to(ROOT).as_posix()]
                if hashlib.sha256(data).hexdigest() != expected:
                    raise SystemExit('input differs from verified v2: ' + name)
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), 0o600, 0
                tf.addfile(info, io.BytesIO(data))
    payload = payload_io.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    header = (ROOT / 'src/mt/single_file_header.sh.in').read_bytes()
    release = header.replace(b'__PAYLOAD_SHA256__', digest.encode()) + base64.encodebytes(payload)
    actual = hashlib.sha256(release).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as f:
        f.write(release)
    result = {'output': str(args.output), 'sha256': actual,
              'byte_identical_to_v2': actual == meta['release_sha256']}
    print(json.dumps(result, ensure_ascii=False))
    if not result['byte_identical_to_v2']:
        raise SystemExit('not byte-identical: check Python/zlib versions; do not replace a verified release')


if __name__ == '__main__':
    main()
