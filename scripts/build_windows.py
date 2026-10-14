"""Build a self-contained Windows folder/ZIP without modifying source config.

python scripts/build_windows.py --engine-release-dir Pikafish.2026-09-06
Only trusted official engine releases should be used. Does not publish anything.
"""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ENGINE_TAG = 'Pikafish-2026-09-06'


def sha256(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def clean_config(config):
    for platform in ('TT', 'JJ'):
        config[platform]['regions'] = {}
    config.update(platform='TT', analysis_mode='continuous', board_index=0, theme='light',
                  engine_params={'movetime': '3000', 'depth': '20', 'goParam': 'movetime'})
    return config


def download(url, target):
    if not target.exists():
        request = urllib.request.Request(url, headers={'User-Agent': 'ChessHelper-build'})
        with urllib.request.urlopen(request, timeout=120) as response, target.open('wb') as out:
            shutil.copyfileobj(response, out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine-release-dir', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.maxsize <= 2**32:
        parser.error('Build on 64-bit Windows with 64-bit Python 3.11')
    release = args.engine_release_dir.resolve()
    required = ['Pikafish-Windows-x86-64-universal.exe', 'pikafish.nnue',
                'Copying.txt', 'NNUE-License.md', 'AUTHORS']
    for name in required:
        if not (release / name).is_file():
            parser.error('Missing official release file: ' + str(release / name))
    version = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, text=True).strip()
    # Unique paths: never delete or overwrite an earlier build.
    label = time.strftime('%Y%m%d-%H%M%S') + '-' + version
    stage = ROOT / 'build' / label
    stage.mkdir(parents=True, exist_ok=False)
    output = ROOT / 'dist' / label
    source_zip = stage / (ENGINE_TAG + '-source.zip')
    download('https://codeload.github.com/official-pikafish/Pikafish/zip/refs/tags/' + ENGINE_TAG, source_zip)
    with zipfile.ZipFile(source_zip) as archive:
        if not any(name.endswith('/src/Makefile') for name in archive.namelist()):
            raise RuntimeError('Invalid engine source archive')
    assets = stage / 'assets'
    (assets / 'json').mkdir(parents=True)
    # Read committed defaults; never package personal runtime state.
    config = json.loads(subprocess.check_output(['git', 'show', 'HEAD:app/json/game_config.json'], cwd=ROOT))
    (assets / 'json/game_config.json').write_text(json.dumps(clean_config(config), indent=2), encoding='utf-8')
    shutil.copyfile(ROOT / 'app/json/log_config.json', assets / 'json/log_config.json')
    engine_dir = assets / 'Pikafish/src'
    engine_dir.mkdir(parents=True)
    shutil.copyfile(release / required[0], engine_dir / 'pikafish.exe')
    shutil.copyfile(release / 'pikafish.nnue', engine_dir / 'pikafish.nnue')
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed',
           '--name', 'ChessHelper', '--distpath', str(output), '--workpath', str(stage / 'pyinstaller'),
           '--specpath', str(stage), '--paths', str(ROOT),
           '--add-data', str(assets) + ';app',
           '--collect-binaries', 'onnxruntime', '--hidden-import', 'win32gui',
           '--hidden-import', 'win32api', '--hidden-import', 'win32con',
           '--hidden-import', 'win32process']
    for folder in ('models', 'images', 'themes'):
        # Only versioned resources, never runtime debug screenshots.
        names = subprocess.check_output(['git', 'ls-files', 'app/' + folder], cwd=ROOT, text=True).splitlines()
        for name in names:
            path = Path(name)
            if path.suffix == '.py':
                continue
            cmd += ['--add-data', str(ROOT / path) + ';' + path.parent.as_posix()]
    for module in ('torch', 'tensorflow', 'matplotlib', 'pandas', 'IPython', 'pytest'):
        cmd += ['--exclude-module', module]
    cmd.append(str(ROOT / 'app/portable_entry.py'))
    subprocess.run(cmd, cwd=ROOT, check=True)
    bundle = output / 'ChessHelper'
    licenses = bundle / 'licenses'
    licenses.mkdir()
    shutil.copyfile(ROOT / 'LICENSE', licenses / 'ChessHelper-LICENSE.txt')
    pikafish = licenses / 'Pikafish'
    pikafish.mkdir()
    for name in required[2:]:
        shutil.copyfile(release / name, pikafish / name)
    shutil.copyfile(source_zip, pikafish / source_zip.name)
    python_license = next((p for p in (Path(sys.base_prefix) / 'LICENSE_PYTHON.txt',
                                      Path(sys.base_prefix) / 'LICENSE.txt') if p.is_file()), None)
    if python_license is None:
        raise RuntimeError('Python license missing; refusing to assemble release ZIP')
    shutil.copyfile(python_license, licenses / 'Python-LICENSE.txt')
    import PySide6
    from PySide6.QtCore import qVersion
    qt = licenses / 'Qt'
    qt.mkdir()
    for name in ('LGPL-3.0-only.txt', 'GPL-3.0-only.txt'):
        download('https://raw.githubusercontent.com/qt/qtbase/v' + qVersion() + '/LICENSES/' + name,
                 qt / name)
    (qt / 'SOURCES.txt').write_text(
        'Qt ' + qVersion() + '\nhttps://download.qt.io/archive/qt/' + '.'.join(qVersion().split('.')[:2]) +
        '/' + qVersion() + '/submodules/\nPySide6 ' + PySide6.__version__ +
        '\nhttps://github.com/qtproject/pyside-pyside-setup/tree/v' + PySide6.__version__ +
        '\nLibraries are dynamically linked; users may replace compatible library files and debug their modifications.\n',
        encoding='utf-8')
    # Installed distribution metadata carries notices for Python dependencies.
    inventory = []
    for dist in metadata.distributions():
        name = dist.metadata.get('Name', 'unknown')
        copied = []
        for item in dist.files or []:
            if any(word in str(item).lower() for word in ('license', 'copying', 'notice')):
                src = Path(dist.locate_file(item))
                if src.is_file() and src.suffix.lower() not in ('.py', '.pyc', '.dll', '.pyd'):
                    dest = licenses / 'python' / name / str(item).replace('..', '_').replace(':', '_')
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest)
                    copied.append(str(dest.relative_to(bundle)))
        inventory.append({'name': name, 'version': dist.version, 'notices': copied})
    (licenses / 'python-environment.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    shutil.copyfile(ROOT / 'docs/windows-portable.md', bundle / '使用说明.md')
    manifest = {'source_commit': version, 'engine_tag': ENGINE_TAG,
                'engine_sha256': sha256(engine_dir / 'pikafish.exe'),
                'nnue_sha256': sha256(engine_dir / 'pikafish.nnue'),
                'engine_source_sha256': sha256(source_zip),
                'python': sys.version, 'pyinstaller': metadata.version('pyinstaller')}
    (bundle / 'build-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    archive = shutil.make_archive(str(output / 'ChessHelper-Windows-x64'), 'zip', output, 'ChessHelper')
    Path(archive + '.sha256').write_text(sha256(archive) + '  ' + Path(archive).name + '\n', encoding='ascii')
    print('Portable build:', archive)


if __name__ == '__main__':
    main()
