#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 jkHXQ
"""Build the v2 module in a NEW directory from a prepared, matching kernel tree.

This is the original v2 command sequence with explicit path options and the
already-verified ABI metadata, so redistributing vendor binaries is unnecessary.
It neither prepares/modifies the kernel tree nor loads/unloads the result.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shlex
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel', required=True, type=Path, help='prepared kernel source/header tree')
    ap.add_argument('--output', required=True, type=Path, help='new output directory')
    ap.add_argument('--clang', default='clang')
    ap.add_argument('--ld', default='ld.lld')
    args = ap.parse_args()
    from elftools.elf.elffile import ELFFile
    kernel, out = args.kernel.resolve(), args.output.resolve()
    if out.exists():
        ap.error('output must not already exist')
    for name in ('include/generated/autoconf.h', 'scripts/mod/modpost', 'scripts/module.lds',
                 'include/linux/qcom_scmi_vendor.h', 'drivers/firmware/arm_scmi/protocols.h'):
        if not (kernel / name).is_file():
            ap.error('missing prepared-tree prerequisite: ' + name)
    profile = json.loads((ROOT / 'abi/profile-v2.json').read_text(encoding='utf-8'))
    source = ROOT / 'src/kernel/cpu_voltage_probe.c'
    if hashlib.sha256(source.read_bytes()).hexdigest() != profile['source_sha256']:
        ap.error('source differs from the verified v2 snapshot')
    out.mkdir(parents=True)
    record = {'source_sha256': profile['source_sha256'], 'commands': [], 'runtime_test': 'NOT_RUN'}

    def save():
        (out / 'build-manifest.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')

    def run(argv):
        argv = [str(x) for x in argv]
        p = subprocess.run(argv, capture_output=True)
        record['commands'].append({'argv': argv, 'returncode': p.returncode,
                                   'stdout': p.stdout.decode('utf-8', 'replace'),
                                   'stderr': p.stderr.decode('utf-8', 'replace')})
        save()
        if p.returncode:
            raise SystemExit(p.stderr.decode('utf-8', 'replace') or f'command exited {p.returncode}')
        return p.stdout

    overlay = out / 'include/generated'
    overlay.mkdir(parents=True)
    (overlay / 'utsrelease.h').write_text('#define UTS_RELEASE "' + profile['vermagic'].split()[0] + '"\n')
    resource = run([args.clang, '-print-resource-dir']).decode().strip()
    record['compiler'] = run([args.clang, '--version']).decode()
    flags = ['--target=aarch64-linux-gnu', '-std=gnu11', '-O2', '-nostdinc', '-isystem', resource + '/include',
             '-I' + str(out / 'include')]
    flags += ['-I' + str(kernel / p) for p in (
        'arch/arm64/include', 'arch/arm64/include/generated', 'include', 'arch/arm64/include/uapi',
        'arch/arm64/include/generated/uapi', 'include/uapi', 'include/generated/uapi',
        'drivers/firmware/arm_scmi')]
    flags += ['-include', str(kernel / 'include/linux/kconfig.h'), '-D__KERNEL__', '-DMODULE',
              '-DKBUILD_MODNAME="live_voltage_scmi_v1"', '-DKBUILD_BASENAME="cpu_voltage_probe"',
              '-D__KBUILD_MODNAME=kmod_live_voltage_scmi_v1', '-fno-pic', '-fno-PIE', '-fno-common',
              '-fno-builtin', '-fno-strict-aliasing', '-fno-delete-null-pointer-checks', '-fno-strict-overflow',
              '-fno-omit-frame-pointer', '-fno-optimize-sibling-calls', '-ffixed-x18', '-mgeneral-regs-only',
              '-mno-outline-atomics', '-mcmodel=large', '-mbranch-protection=pac-ret', '-fsanitize=kcfi',
              '-fsanitize=shadow-call-stack', '-fstack-protector-strong', '-mstack-protector-guard=sysreg',
              '-mstack-protector-guard-reg=sp_el0', '-mstack-protector-guard-offset=1568']
    obj, depfile = out / 'cpu_voltage_probe.o', out / 'cpu_voltage_probe.d'
    command = [args.clang, *flags, '-MD', '-MF', depfile, '-c', source, '-o', obj]
    run(command)
    dependencies = depfile.read_text().split(':', 1)[1].replace('\\\n', ' ').split()
    (out / '.cpu_voltage_probe.o.cmd').write_text(
        'savedcmd_' + str(obj) + ' := ' + shlex.join([str(x) for x in command]) + '\n' +
        'deps_' + str(obj) + ' := \\\n' + ''.join('  ' + p + ' \\\n' for p in dependencies) + '\n')
    (out / 'cpu_voltage_probe.mod').write_text(str(obj) + '\n')
    run([kernel / 'scripts/mod/modpost', '-m', '-i', ROOT / 'abi/Module.symvers.v2',
         '-o', out / 'Module.symvers', obj])
    mod_obj = out / 'cpu_voltage_probe.mod.o'
    run([args.clang, *flags, '-c', out / 'cpu_voltage_probe.mod.c', '-o', mod_obj])
    ko = out / 'cpu_voltage_probe.ko'
    run([args.ld, '-r', '--build-id=sha1', '-T', kernel / 'scripts/module.lds', '-o', ko, obj, mod_obj])
    errors = []
    with ko.open('rb') as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name('.symtab')
        magic = next(v[9:].decode() for v in elf.get_section_by_name('.modinfo').data().split(b'\0')
                     if v.startswith(b'vermagic='))
        sym = symtab.get_symbol_by_name('init_module')[0]
        kcfi = elf.get_section(sym['st_shndx']).data()[sym['st_value'] - 4:sym['st_value']].hex()
        raw = elf.get_section_by_name('__versions').data()
        imported = {}
        for i in range(0, len(raw), 64):
            name = raw[i + 8:i + 64].split(b'\0')[0].decode()
            imported[name] = f'0x{struct.unpack_from("<Q", raw, i)[0] & 0xffffffff:08x}'
        if imported != {v['name']: v['crc'] for v in profile['imports']}:
            errors.append('import/CRC mismatch')
        if magic != profile['vermagic']:
            errors.append('vermagic differs from the original target baseline')
        if kcfi != profile['init_kcfi']:
            errors.append('init KCFI mismatch')
        if symtab.get_symbol_by_name('cleanup_module'):
            errors.append('unexpected cleanup_module')
    digest = hashlib.sha256(ko.read_bytes()).hexdigest()
    record.update({'ko_sha256': digest, 'vermagic': magic, 'init_kcfi': kcfi, 'imports': imported,
                   'validation_errors': errors, 'byte_identical_to_verified_v2': digest == profile['ko_sha256']})
    save()
    print(json.dumps({k: record[k] for k in ('ko_sha256', 'validation_errors',
                                           'byte_identical_to_verified_v2', 'runtime_test')}))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
