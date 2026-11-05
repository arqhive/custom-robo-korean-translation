"""Insert the finished Korean images (work/graphics/result).

Result PNGs use the original copies' orientation: UI and map labels as stored in ROM,
sign textures (R...) upright, i.e. vertically flipped against ROM. Colours are the
original 5-bit colours only, so CI8 images are re-indexed into their original palette.

UI bank streams: offset table ROM 0x4F300 (base 0x6D5300). Map labels: table 0x83A98
(base 0x77C590). Sign textures: table 0x82CA4 (base 0x482690, 397 entries). All three
loaders take the size from the stream header, so a stream that grows is appended to
free ROM and only its table entry changes.
"""
import json,struct
from pathlib import Path
import numpy as np
from PIL import Image
from survey_rom import ROOT,decode
from codec import encode

RESULTS=ROOT/'work/graphics/result'
UI_BASE=0x6d5300
TEX_TABLE=0x82ca4;TEX_BASE=0x482690;TEX_COUNT=397
MAP_TABLE=0x83a98;MAP_BASE=0x77c590;MAP_COUNT=13
MODEL_BASE=0x16cac0   # model textures (T...): 20-byte records hold the stream offset from here (sushi menu: 0xb1080)

def load(t):
    a=np.array(Image.open(RESULTS/f"{t['id']}.png").convert('RGBA'))
    assert a.shape==(t['height'],t['width'],4),t['id']
    return a[::-1] if t['id'].startswith('R') else a

def to5551(a):
    return (((a[...,0].astype(np.uint16)>>3)<<11)|((a[...,1].astype(np.uint16)>>3)<<6)|((a[...,2].astype(np.uint16)>>3)<<1)|(a[...,3]>=128)).astype(np.uint16)

def ci8(a,orig):
    pal=np.frombuffer(orig[:512],'>u2')
    want=to5551(a);lut={}
    for i,v in enumerate(pal):lut.setdefault(int(v),i)
    clear=[i for i,v in enumerate(pal) if not v&1]
    idx=np.zeros(want.shape,np.uint8);miss=0
    for v in np.unique(want):
        v=int(v)
        if v in lut:k=lut[v]
        elif not v&1 and clear:k=clear[0]          # any transparent entry
        else:raise AssertionError(('colour not in the original palette',hex(v)))
        idx[want==v]=k
    return orig[:512]+idx.tobytes()

def ci4(a,orig):
    """Model textures (T...): 16-colour palette (32 bytes) then 4-bit pixels, high nibble first."""
    pal=np.frombuffer(orig[:32],'>u2')
    want=to5551(a);lut={}
    for i,v in enumerate(pal):lut.setdefault(int(v),i)
    idx=np.zeros(want.shape,np.uint8)
    for v in np.unique(want):
        assert int(v) in lut,('colour not in the original palette',hex(int(v)))
        idx[want==v]=lut[int(v)]
    f=idx.reshape(-1)
    return orig[:32]+((f[::2]<<4)|f[1::2]).astype(np.uint8).tobytes()

def place(rom,source,append,old,packed,label):
    stored=struct.unpack_from('>I',source,old)[0]
    if len(packed)<=stored:
        rom[old:old+stored]=packed+bytes(stored-len(packed));return old
    return append(packed,label)

def apply(rom,source,append):
    targets=json.loads((ROOT/'manifests/image-translation-targets.json').read_text(encoding='utf-8'))
    files={p.stem for p in RESULTS.glob('*.png')};assert files=={t['id'] for t in targets},files^{t['id'] for t in targets}
    tex=list(struct.unpack_from('>%dI'%TEX_COUNT,source,TEX_TABLE))
    maps=list(struct.unpack_from('>%dI'%MAP_COUNT,source,MAP_TABLE))
    report=[]
    for t in targets:
        a=load(t);orig,_=decode(source,t['rom_stream'])
        if t['format']=='CI8':new=ci8(a,orig)
        elif t['format']=='CI4':new=ci4(a,orig)
        elif t['format']=='RGBA32':new=a.tobytes()
        else:
            o=t['decoded_offset'];px=to5551(a).astype('>u2').tobytes();new=orig[:o]+px+orig[o+len(px):]
        assert len(new)==len(orig),t['id']
        packed=encode(new);assert decode(packed,0)[0]==new
        pos=place(rom,source,append,t['rom_stream'],packed,t['id'])
        if pos!=t['rom_stream']:
            if t['id'].startswith('U'):struct.pack_into('>I',rom,t['pointer_entry'],pos-UI_BASE)
            elif t['id'].startswith('T'):   # model texture record (w/h, flags, offset from MODEL_BASE, 0, RAM): same as V2 B01
                e=t['pointer_entry'];assert struct.unpack_from('>I',source,e)[0]==t['rom_stream']-MODEL_BASE,t['id']
                struct.pack_into('>I',rom,e,pos-MODEL_BASE)
            elif t['id'].startswith('L'):struct.pack_into('>I',rom,MAP_TABLE+4*maps.index(t['rom_stream']-MAP_BASE),pos-MAP_BASE)
            else:
                hits=[i for i,v in enumerate(tex) if v+TEX_BASE==t['rom_stream']];assert hits,t['id']
                for i in hits:struct.pack_into('>I',rom,TEX_TABLE+4*i,pos-TEX_BASE)
        assert decode(rom,pos)[0]==new
        report.append({'id':t['id'],'moved':pos!=t['rom_stream']})
    return {'inserted':len(report),'source':str(RESULTS),'moved':[r['id'] for r in report if r['moved']]}
