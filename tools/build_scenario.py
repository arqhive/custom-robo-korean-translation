"""Build translated scenario batches with a separate Korean glyph cache."""
from pathlib import Path
import json,struct,hashlib
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from translation_catalog import ROOT,collect,encode_text
from build_opening_probe import crc6102
from codec import encode
from survey_rom import decode
import font_cache

def main():
    source=(ROOT/'Custom Robo (Japan).z64').read_bytes();rom=bytearray(source)
    rows,changed,mapping,progress=collect()
    assert not progress['byte_budget_failures'],progress['byte_budget_failures']
    assert progress['max_distinct_hangul_per_message']<=120
    assert crc6102(source)==source[16:24]
    free=(len(source.rstrip(b'\xff'))+15)&~15
    allocations=[]
    def append(data,label):
        nonlocal free
        start=free;assert start+len(data)<=len(rom)
        assert source[start:start+len(data)]==b'\xff'*len(data)
        rom[start:start+len(data)]=data;free=(start+len(data)+15)&~15
        allocations.append({'label':label,'offset':start,'bytes':len(data)})
        return start
    # Re-run the original initializer oracle on every build, not a stale cache.
    japanese=font_cache.original_expanded(source)
    original_texture_rom=append(japanese,'original_font_i4')
    fontpath=Path('C:/Users/hgyst/AppData/Local/Microsoft/Windows/Fonts/Galmuri11.ttf')
    font=ImageFont.truetype(str(fontpath),11);ko=[]
    for c in mapping:
        im=Image.new('1',(12,12));ImageDraw.Draw(im).text((0,0),c,font=font,fill=1)
        assert im.getbbox()
        bits=np.packbits(np.array(im,dtype=np.uint8).reshape(-1)).tobytes()
        ko.append(font_cache.expand(bits))
    korean_texture_rom=append(b''.join(ko),'korean_font_i4')
    font_report=font_cache.patch(rom,original_texture_rom,korean_texture_rom,len(mapping))
    files=json.loads((ROOT/'manifests/script-files.json').read_text(encoding='utf-8'))
    scripts={};entry_checks=[]
    for row in changed:
        fid=row['script'];raw=scripts.setdefault(fid,bytearray((ROOT/f'work/extracted/scripts/{fid:03d}.bin').read_bytes()))
        p=row['offset'];old=row['source'].encode('euc_jp');assert raw[p:p+len(old)]==old
        b=encode_text(row['translation'],mapping);assert len(b)<=len(old)
        raw[p:p+len(old)+1]=b+bytes(len(old)+1-len(b))
        entry_checks.append({'id':row['id'],'old_bytes':len(old),'new_bytes':len(b)})
    locations=[]
    for fid,raw in sorted(scripts.items()):
        f=files[fid];packed=encode(bytes(raw))
        if len(packed)<=f['compressed_size']:
            address=f['rom_offset'];rom[address:address+f['compressed_size']]=packed+bytes(f['compressed_size']-len(packed))
        else:address=append(packed,f'script_{fid:03d}');struct.pack_into('>I',rom,f['table_entry'],address-0x31c290)
        assert decode(rom,address)[0]==raw
        before=(ROOT/f'work/extracted/scripts/{fid:03d}.bin').read_bytes()
        assert before[:f['string_pool']]==raw[:f['string_pool']]
        locations.append({'script':fid,'rom_offset':address,'compressed_bytes':len(packed)})
    assert rom[0x457c0:0x46b0a]==source[0x457c0:0x46b0a]
    assert rom[0x1195a0:0x12095c]==source[0x1195a0:0x12095c]
    rom[16:24]=crc6102(rom)
    out=ROOT/'work/runtime/Custom Robo (Japan) [KO scenario candidate].z64';out.write_bytes(rom)
    report={'status':'candidate_not_runtime_validated','file':str(out.relative_to(ROOT)),
            'sha256':hashlib.sha256(rom).hexdigest(),'original_sha256':hashlib.sha256(source).hexdigest(),
            'crc6102':rom[16:24].hex(),'font':font_report,'font_source':str(fontpath),
            'code_mapping':{k:v.hex() for k,v in mapping.items()},'glyph_count':len(mapping),
            'original_texture_rom':original_texture_rom,'korean_texture_rom':korean_texture_rom,
            'translated_entries':len(changed),'direct_translation_entries':progress['directly_translated_entries'],
            'completed_dialogue_sections':progress['completed_dialogue_sections'],
            'max_distinct_hangul_per_message':progress['max_distinct_hangul_per_message'],
            'entry_checks':entry_checks,'script_locations':locations,'allocations':allocations,
            'literal_encoding_checked':True,'controls_preserved':True,'script_offsets_preserved':True,
            'runtime_tested':False,'full_translation':False}
    (ROOT/'manifests/scenario-build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['file','translated_entries','glyph_count','completed_dialogue_sections','crc6102']}))

if __name__=='__main__':main()
