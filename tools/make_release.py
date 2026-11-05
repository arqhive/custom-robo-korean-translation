"""Make the distributable patch from a verified build: xdelta (applied back and hashed)."""
from pathlib import Path
import hashlib,subprocess,sys,json,shutil
ROOT=Path(__file__).resolve().parents[1]
XD=ROOT/'tools/bin/xdelta3.exe'

def main(version,build_name):
    src=ROOT/'Custom Robo (Japan).z64';out=ROOT/'build'/build_name
    ver=json.loads((ROOT/'manifests/full-build-verification.json').read_text(encoding='utf-8'))
    assert ver['scenario']['mismatch']==0 and ver['raw']['segments_with_japanese']==0 and ver['crc_ok']
    rel=ROOT/'release'/version;rel.mkdir(parents=True,exist_ok=True)
    patch=rel/f'NCXJ_KPatch_{version}.xdelta'
    if patch.exists():patch.unlink()
    subprocess.run([str(XD),'-9','-S','djw','-e','-s',str(src),str(out),str(patch)],check=True)
    test=rel/'_applied.z64'
    subprocess.run([str(XD),'-d','-f','-s',str(src),str(patch),str(test)],check=True)
    h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    assert h(test)==h(out);test.unlink()
    readme=(ROOT/'docs/README_KO.txt').read_text(encoding='utf-8')
    (rel/'README_KO.txt').write_text(readme.replace('{VERSION}',version).replace('{RESULT_SHA256}',h(out)).replace('{RESULT_MD5}',hashlib.md5(out.read_bytes()).hexdigest()).replace('{RESULT_CRC32}','%08X'%(__import__('zlib').crc32(out.read_bytes())&0xffffffff)),encoding='utf-8')
    sums=''.join(f'{h(p)}  {p.name}\n' for p in sorted(rel.iterdir()) if p.name in (patch.name,'README_KO.txt'))
    (rel/'SHA256SUMS.txt').write_text(sums,encoding='utf-8')
    # the release carries one zip: the xdelta and README_KO.txt (11/05)
    import zipfile
    zp=rel/f'NCXJ_KPatch_{version}.zip'
    with zipfile.ZipFile(zp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in (patch,rel/'README_KO.txt'):z.write(p,p.name)
    print(json.dumps({'zip':str(zp.relative_to(ROOT)),'patch':str(patch.relative_to(ROOT)),'bytes':patch.stat().st_size,'result_sha256':h(out)}))

if __name__=='__main__':main(sys.argv[1],sys.argv[2])
