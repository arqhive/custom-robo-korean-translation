"""Export image banks, actor frames, portraits and embedded material textures.

Actor/portrait associations follow the actual scenario renderer tables. Model
materials use shared palettes plus image arrays at the tail of each model;
their stored image-array pointer is checked before extraction.
"""
from pathlib import Path
import json,struct,hashlib,math,collections,shutil
import numpy as np
from PIL import Image
from survey_rom import ROOT
from extract_assets import rgba16

def paletted(data,width,height,bits):
    colors=1<<bits;palette_bytes=colors*2
    pal=np.array(rgba16(data[:palette_bytes],colors,1)).reshape(colors,4)
    size=width*height
    if bits==8:indices=np.frombuffer(data[palette_bytes:palette_bytes+size],dtype=np.uint8)
    else:
        packed=np.frombuffer(data[palette_bytes:palette_bytes+(size+1)//2],dtype=np.uint8)
        indices=np.empty(len(packed)*2,dtype=np.uint8);indices[::2]=packed>>4;indices[1::2]=packed&15
        indices=indices[:size]
    assert len(indices)==size
    return Image.fromarray(pal[indices].reshape(height,width,4))

def main():
    rom=(ROOT/'Custom Robo (Japan).z64').read_bytes()
    streams=json.loads((ROOT/'manifests/compressed-streams.json').read_text())
    dest=ROOT/'work/extracted/all-images';dest.mkdir(exist_ok=True)
    prior=ROOT/'manifests/all-images.json'
    if prior.exists():
        for old in json.loads(prior.read_text(encoding='utf-8')):
            if old['category']=='model-materials':
                p=(ROOT/old['file']).resolve()
                assert p.is_relative_to(dest.resolve())
                if p.exists():p.unlink()
    entries=[];covered=set();actors=[];portraits=[];unresolved=[]
    def save(im,category,name,info):
        folder=dest/category;folder.mkdir(exist_ok=True)
        p=folder/(name+'.png');im.save(p)
        entries.append(dict(id=name,category=category,file=str(p.relative_to(ROOT)),width=im.width,height=im.height,
                            rgba_sha256=hashlib.sha256(im.convert('RGBA').tobytes()).hexdigest(),**info))
    def va(address):return 0x6bec0+address-0x801688b0
    def cstring(address):
        p=va(address);return rom[p:rom.index(b'\0',p)].decode('euc_jp')
    base=va(0x80180668);actor_count=struct.unpack_from('>I',rom,base-8)[0]
    actor_rows=[]
    for i in range(actor_count):
        p=base+i*0x510;ptr,count,start=struct.unpack_from('>III',rom,p)
        actor_rows.append({'id':i,'name':cstring(ptr),'declared_frames':count,'start':0x4d6cb0+start,
                           'palette_rom_offset':p+0x310,'descriptor_rom_offset':p})
    for i,a in enumerate(actor_rows):
        end=actor_rows[i+1]['start'] if i+1<len(actor_rows) else 0x657f20
        frames=[r for r in streams if a['start']<=r['offset']<end]
        assert len(frames)==a['declared_frames'],(a,len(frames))
        palette=rom[a['palette_rom_offset']:a['palette_rom_offset']+512]
        atlas=Image.new('RGBA',(32*12,32*math.ceil(len(frames)/12)))
        for j,r in enumerate(frames):
            raw=(ROOT/r['file']).read_bytes();assert len(raw)==1024
            im=paletted(palette+raw,32,32,8)
            save(im,'actors',f'A{i:02d}-{j:03d}',{'format':'CI8','rom_stream':r['offset'],
                 'actor_id':i,'actor_name':a['name'],'palette_rom_offset':a['palette_rom_offset'],
                 'source_sha256':hashlib.sha256(raw).hexdigest(),'orientation':'native'})
            atlas.paste(im,(j%12*32,j//12*32));covered.add(r['offset'])
        af=dest/'actor-atlases';af.mkdir(exist_ok=True);atlas.save(af/f'A{i:02d}.png')
        actors.append(dict(a,extracted_frames=len(frames),atlas=str((af/f'A{i:02d}.png').relative_to(ROOT))))
    n=struct.unpack_from('>I',rom,va(0x8017e180))[0];portrait_bytes=0
    for i in range(n):
        ptr,count,relative=[struct.unpack_from('>I',rom,va(address)+i*4)[0] for address in [0x8017e184,0x8017e1d8,0x8017e22c]]
        p=0x657f20+relative;palette=rom[p:p+512];name=cstring(ptr)
        for j in range(count):
            start=p+512+j*0x900;raw=rom[start:start+0x900]
            save(paletted(palette+raw,48,48,8),'portraits',f'F{i:02d}-{j:02d}',
                 {'format':'CI8','rom_offset':start,'palette_rom_offset':p,'character_name':name,
                  'source_sha256':hashlib.sha256(raw).hexdigest(),'orientation':'native'})
        portraits.append({'id':i,'name':name,'expressions':count,'rom_offset':p})
        portrait_bytes+=512+count*0x900
    assert portrait_bytes==0x69f320-0x657f20
    for r in json.loads((ROOT/'manifests/images-confirmed.json').read_text()):
        im=Image.open(ROOT/r['file']).convert('RGBA')
        # Preserve UV orientation exactly. Translation review can flip the view.
        save(im,'world-textures',r['id'],{'format':r['format'],'rom_stream':r['rom_stream'],
             'decoded_offset':r['decoded_offset'],'orientation':'native_uv'})
        covered.add(r['rom_stream'])
    for r in json.loads((ROOT/'manifests/ui-images.json').read_text()):
        save(Image.open(ROOT/r['file']).convert('RGBA'),'ui',r['id'],
             {'format':r['format'],'rom_stream':r['rom_stream'],'orientation':'native',
              'translation_target':r['translation_target']})
        covered.add(r['rom_stream'])
    def pow2(x):return x>0 and not x&(x-1)
    def squareish(pixels):
        log=pixels.bit_length()-1;return 1<<((log+1)//2),1<<(log//2)
    embedded_ranges=[(0x255fb0,0x2ceaa0,12),(0x2ceaa0,0x2f1b40,8)]
    for r in streams:
        offset=r['offset'];raw=(ROOT/r['file']).read_bytes()
        if 0x16cac0<=offset<0x1ad040:
            if pow2(len(raw)-32):bits=4;w,h=squareish((len(raw)-32)*2);im=paletted(raw,w,h,bits);fmt='CI4'
            elif pow2(len(raw)-512):bits=8;w,h=squareish(len(raw)-512);im=paletted(raw,w,h,bits);fmt='CI8'
            elif len(raw) in (2048,4096):
                w=32;h=len(raw)//4//w;im=Image.fromarray(np.frombuffer(raw,dtype=np.uint8).reshape(h,w,4));fmt='RGBA8888'
            else:unresolved.append({'rom_stream':offset,'reason':'unrecognized flat model texture','bytes':len(raw)});continue
            save(im,'robot-textures',f'T{offset:08X}',{'format':fmt,'rom_stream':offset,
                 'orientation':'native_uv','dimension_source':'pixel count; square or 2:1 power-of-two texture'})
            covered.add(offset)
        elif 0x1ad040<=offset<0x1cf2c0:
            assert len(raw)==4608
            save(paletted(raw,64,64,8),'robot-icons',f'I{offset:08X}',{'format':'CI8','rom_stream':offset,'orientation':'native'})
            covered.add(offset)
        elif 0x2f1b40<=offset<0x319a00:
            assert len(raw)==20992
            save(paletted(raw,256,80,8),'battle-backgrounds',f'B{offset:08X}',
                 {'format':'CI8','rom_stream':offset,'orientation':'native','dimension_source':'row coherence and visual verification'})
            covered.add(offset)
        elif 0x77c590<=offset<0x77d700:
            h=16;w=(len(raw)-512)//h
            assert 512+w*h==len(raw)
            save(paletted(raw,w,h,8),'map-labels',f'L{offset:08X}',
                 {'format':'CI8','rom_stream':offset,'orientation':'native','translation_target':True})
            covered.add(offset)
        else:
            if offset not in covered and len(raw)>=8:
                size,wx,hy,count=struct.unpack_from('>IBBH',raw)
                if size==len(raw) and 1<=wx<=10 and 1<=hy<=10 and 1<=count<=32:
                    w,h=1<<wx,1<<hy
                    if 8+count*w*h*4==len(raw):
                        for j in range(count):
                            start=8+j*w*h*4
                            im=Image.fromarray(np.frombuffer(raw[start:start+w*h*4],dtype=np.uint8).reshape(h,w,4))
                            save(im,'world-textures',f'R{offset:08X}-{j:02d}',{'format':'RGBA8888',
                                 'rom_stream':offset,'decoded_offset':start,'orientation':'native_uv'})
                        covered.add(offset)
            for lo,hi,prefix in embedded_ranges:
                if not lo<=offset<hi:continue
                if offset in (0x2e2540,0x2e6298,0x2ea0f4,0x2ee07c):
                    # Four palette variants of one model with four distinct UV
                    # texture dimensions, followed by its 12-part geometry table.
                    assert struct.unpack_from('>I',raw,0x1904)[0]==0x1934
                    for j,(p,w,h) in enumerate([(4,32,32),(0x604,32,32),(0xc04,16,16),(0xf04,64,32)]):
                        save(paletted(raw[p:p+512+w*h],w,h,8),'model-materials',f'M{offset:08X}-{j:02d}',
                             {'format':'CI8','rom_stream':offset,'palette_decoded_offset':p,
                              'decoded_offset':p+512,'orientation':'native_uv','dimension_source':'shared model UV layout'})
                    covered.add(offset);break
                w,h=(raw[10],raw[11]) if prefix==12 else (raw[5],raw[6])
                count=raw[9] if prefix==12 else 1
                if not(8<=w<=128 and 8<=h<=128 and 1<=count<=16):
                    unresolved.append({'rom_stream':offset,'reason':'unrecognized material header','bytes':len(raw)});break
                start=len(raw)-w*h*count
                pointer_at=prefix+512+(32 if prefix==12 else 8)
                if start<prefix+512 or struct.unpack_from('>I',raw,pointer_at)[0]!=start:
                    unresolved.append({'rom_stream':offset,'reason':'short material texture','bytes':len(raw)});break
                for j in range(count):
                    pixels=start+j*w*h
                    save(paletted(raw[prefix:prefix+512]+raw[pixels:pixels+w*h],w,h,8),'model-materials',f'M{offset:08X}-{j:02d}',
                         {'format':'CI8','rom_stream':offset,'palette_decoded_offset':prefix,'decoded_offset':pixels,'orientation':'native_uv',
                          'dimension_source':'model header and checked image-array pointer'})
                covered.add(offset);break
    recognized_nonimage={r['rom_offset'] for r in json.loads((ROOT/'manifests/script-files.json').read_text())}
    for r in streams:
        o=r['offset']
        if 0x120960<=o<0x16cac0 or 0x3f61d0<=o<0x482690:recognized_nonimage.add(o)
        if 0x745dd0<=o<0x77c590:
            raw=(ROOT/r['file']).read_bytes();count=struct.unpack_from('>I',raw,4)[0]
            assert 1<=count<=8
            offsets=struct.unpack_from('>'+str(count)+'I',raw,8)
            assert offsets[0]==12+4*count and all(0<=p<len(raw) for p in offsets)
            recognized_nonimage.add(o)
    unexplained=[{'rom_stream':r['offset'],'decoded_bytes':r['decoded_size'],'file':r['file']} for r in streams
                 if r['offset'] not in covered|recognized_nonimage]
    (ROOT/'manifests/all-images.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'manifests/actor-images.json').write_text(json.dumps(actors,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'manifests/portrait-images.json').write_text(json.dumps(portraits,ensure_ascii=False,indent=2),encoding='utf-8')
    report={'image_frames':len(entries),'categories':dict(collections.Counter(r['category'] for r in entries)),
            'actor_count':len(actors),'portrait_characters':len(portraits),'portrait_bank_bytes_verified':portrait_bytes,
            'image_streams_covered':len(covered),'known_nonimage_streams':len(recognized_nonimage),
            'unresolved_materials':unresolved,'unclassified_streams':unexplained,
            'all_images_confirmed_complete':not(unresolved or unexplained),
            'original_rom_sha256':hashlib.sha256(rom).hexdigest()}
    (ROOT/'manifests/full-image-extraction.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('unresolved_materials','unclassified_streams')},ensure_ascii=False))
    print('Unclassified streams:',len(unexplained),'unresolved materials:',len(unresolved))

if __name__=='__main__':main()
