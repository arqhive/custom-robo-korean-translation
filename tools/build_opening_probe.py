"""Limited opening-scene Korean probe, not a complete translation build.

Reuses glyph slots absent from the extracted text corpus. Does not change RAM
layout or require an Expansion Pak. All non-translated strings retain offsets.
"""
import json, re, struct, hashlib
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from survey_rom import ROOT, decode
from codec import encode


def crc6102(b):
    t1=t2=t3=t4=t5=t6=0xf8ca4ddc
    for p in range(0x1000,0x101000,4):
        d=struct.unpack_from('>I',b,p)[0];k=(t6+d)&0xffffffff
        if k<t6:t4=(t4+1)&0xffffffff
        t6=k;t3^=d;n=d&31;r=((d<<n)|(d>>(32-n)))&0xffffffff
        t5=(t5+r)&0xffffffff;t2^=r if t2>d else t6^d
        t1=(t1+(t5^d))&0xffffffff
    return struct.pack('>II',t6^t4^t3,t5^t2^t1)


def main():
    original=(ROOT/'Custom Robo (Japan).z64').read_bytes();rom=bytearray(original)
    assert crc6102(original)==original[16:24]
    entries=json.loads((ROOT/'work/translation/source-texts.json').read_text(encoding='utf-8'))
    byid={r['id']:r for r in entries}
    translations=json.loads((ROOT/'work/translation/opening-ko.json').read_text(encoding='utf-8'))
    glyphs=json.loads((ROOT/'manifests/font.json').read_text(encoding='utf-8'))
    unused=json.loads((ROOT/'manifests/font-unused-candidates.json').read_text(encoding='utf-8'))
    unused=[r for r in unused if '\u4e00'<=r['char']<='\u9fff']
    hangul=sorted(set(c for t in translations.values() for c in t if '가'<=c<='힣'))
    assert len(hangul)<=len(unused),(len(hangul),len(unused))
    fontpath=Path('C:/Users/hgyst/AppData/Local/Microsoft/Windows/Fonts/Galmuri11.ttf')
    font=ImageFont.truetype(str(fontpath),11)
    table=[];mapping={};removed=[];preview=[]
    replacements={u['index']:(c,((0x81+i//94)<<8)|(0xa1+i%94)) for i,(u,c) in enumerate(zip(unused,hangul))}
    for old in glyphs:
        idx=old['index'];p=old['rom_offset'];bits=original[p:p+18]
        if idx in replacements:
            char,code=replacements[idx]
            im=Image.new('1',(12,12));ImageDraw.Draw(im).text((0,0),char,font=font,fill=1)
            assert im.getbbox() is not None
            bits=np.packbits(np.array(im,dtype=np.uint8).reshape(-1)).tobytes()
            assert len(bits)==18
            table.append((code,12,bits));mapping[char]=f'{code:04x}'
            removed.append(old['char']);preview.append(im)
        else:table.append((int(old['euc_jp'],16),old['advance'],bits))
    table.sort(key=lambda x:x[0]);assert len(table)==1646 and len({x[0] for x in table})==1646
    for i,(code,advance,bits) in enumerate(table):
        struct.pack_into('>H',rom,0x457c0+2*i,code)
        rom[0x4649c+i]=advance;rom[0x1195a0+i*18:0x1195a0+(i+1)*18]=bits
    def textbytes(s):
        chunks=[]
        for token in re.split(r'(\$(?:[A-Z]\d{2}|[A-Z])|#[a-zA-Z])',s):
            if re.fullmatch(r'\$(?:[A-Z]\d{2}|[A-Z])|#[a-zA-Z]',token):
                chunks.append(token.encode('ascii'));continue
            for c in token:
                if c==' ':c='\u3000'
                elif c=="'":c='’'
                elif c=='"':c='”'
                elif 0x21<=ord(c)<=0x7e:c=chr(ord(c)+0xfee0)
                encoded=bytes.fromhex(mapping[c]) if c in mapping else c.encode('euc_jp')
                assert len(encoded)==2,repr(c)
                chunks.append(encoded)
        return b''.join(chunks)
    files=json.loads((ROOT/'manifests/script-files.json').read_text())
    changed={};checks=[]
    controls=r'\$(?:[A-Z]\d{2}|[A-Z])|#[a-zA-Z]'
    for ident,text in translations.items():
        row=byid[ident];raw=changed.setdefault(row['script'],bytearray((ROOT/f'work/extracted/scripts/{row["script"]:03d}.bin').read_bytes()))
        assert re.findall(controls,text)==re.findall(controls,row['source']),ident
        encoded=textbytes(text);assert len(encoded)<=row['bytes'],(ident,len(encoded),row['bytes'])
        start=row['offset'];assert raw[start:start+row['bytes']]==row['source'].encode('euc_jp')
        raw[start:start+row['bytes']+1]=encoded+bytes(row['bytes']+1-len(encoded))
        checks.append({'id':ident,'old_bytes':row['bytes'],'new_bytes':len(encoded)})
    free=(len(original.rstrip(b'\xff'))+15)&~15
    relocations=[]
    for fid,raw in changed.items():
        f=files[fid];compressed=encode(bytes(raw))
        if len(compressed)<=f['compressed_size']:
            start=f['rom_offset'];rom[start:start+f['compressed_size']]=compressed+bytes(f['compressed_size']-len(compressed))
        else:
            start=free;assert start+len(compressed)<=len(rom)
            assert original[start:start+len(compressed)]==b'\xff'*len(compressed)
            rom[start:start+len(compressed)]=compressed
            struct.pack_into('>I',rom,f['table_entry'],start-0x31c290)
            relocations.append({'script':fid,'from':f['rom_offset'],'to':start,'size':len(compressed)})
            free=(start+len(compressed)+15)&~15
        assert decode(rom,start)[0]==raw
        before=(ROOT/f'work/extracted/scripts/{fid:03d}.bin').read_bytes()
        assert raw[:f['string_pool']]==before[:f['string_pool']]
    rom[16:24]=crc6102(rom)
    out=ROOT/'build/Custom Robo (Japan) [KO opening probe].z64';out.write_bytes(rom)
    report={'status':'opening_probe_not_full_translation','file':str(out.relative_to(ROOT)),
            'sha256':hashlib.sha256(rom).hexdigest(),'original_sha256':hashlib.sha256(original).hexdigest(),
            'translated_entries':len(translations),'hangul_glyphs':len(hangul),'glyph_font':str(fontpath),
            'glyph_font_sha256':hashlib.sha256(fontpath.read_bytes()).hexdigest(),
            'code_mapping':mapping,'replaced_unused_candidates':removed,
            'crc6102':rom[16:24].hex(),'controls_preserved':True,'script_code_and_offsets_preserved':True,
            'compressed_roundtrip':True,'all_dialogue_literals_two_bytes':True,'runtime_tested':False,'entry_checks':checks,'relocations':relocations,
            'limitations':['Only opening dialogue is translated.','Unused glyph selection is based on extracted text, not full gameplay coverage.','Runtime validation pending.']}
    (ROOT/'manifests/opening-probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    sheet=Image.new('RGB',(20*36,((len(preview)+19)//20)*36),'#303840')
    for i,im in enumerate(preview):sheet.paste('white',(i%20*36,i//20*36),im.resize((36,36),Image.Resampling.NEAREST))
    sheet.save(ROOT/'work/research/korean-glyph-probe.png')
    print(json.dumps({k:report[k] for k in ('file','translated_entries','hangul_glyphs','crc6102','runtime_tested')}))


if __name__=='__main__':main()
