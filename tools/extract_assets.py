"""Extract confirmed font and self-describing RGBA16 texture packets.
Does not claim untyped model/sprite data have been fully classified.
"""
from pathlib import Path
import json,struct,hashlib,math,html
import numpy as np
from PIL import Image,ImageDraw
from survey_rom import ROOT

def rgba16(raw,w,h):
    v=np.frombuffer(raw,dtype='>u2').astype(np.uint16).reshape(h,w)
    a=np.empty((h,w,4),np.uint8)
    for i,shift in enumerate((11,6,1)):
        n=(v>>shift)&31;a[:,:,i]=(n<<3)|(n>>2)
    a[:,:,3]=(v&1)*255
    return Image.fromarray(a)

def fonts(rom):
    out=ROOT/'work/extracted/font';out.mkdir(parents=True,exist_ok=True);chars=[]
    for i in range(1646):
        c=struct.unpack_from('>H',rom,0x457c0+2*i)[0];s=c.to_bytes(2,'big').decode('euc_jp')
        raw=rom[0x1195a0+i*18:0x1195a0+(i+1)*18]
        a=np.unpackbits(np.frombuffer(raw,dtype=np.uint8)).reshape(12,12)*255
        Image.fromarray(a).save(out/f'{i:04d}.png')
        chars.append({'index':i,'euc_jp':f'{c:04x}','char':s,'advance':rom[0x4649c+i],'rom_offset':0x1195a0+i*18})
    (ROOT/'manifests/font.json').write_text(json.dumps(chars,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    rom=(ROOT/'Custom Robo (Japan).z64').read_bytes();fonts(rom)
    rows=json.loads((ROOT/'manifests/compressed-streams.json').read_text())
    out=ROOT/'work/extracted/images';out.mkdir(parents=True,exist_ok=True);images=[]
    for row in rows:
        b=(ROOT/row['file']).read_bytes()
        if len(b)<8:continue
        size,wx,hy,n=struct.unpack_from('>IBBH',b)
        if not(size==len(b) and 1<=wx<=10 and 1<=hy<=10 and 1<=n<=32):continue
        w,h=1<<wx,1<<hy;frame=w*h*2
        if 8+n*frame!=len(b):continue
        for i in range(n):
            name=f'R{row["offset"]:08X}-{i:02d}';raw=b[8+i*frame:8+(i+1)*frame]
            im=rgba16(raw,w,h);im.save(out/f'{name}.png')
            images.append({'id':name,'rom_stream':row['offset'],'decoded_offset':8+i*frame,'width':w,'height':h,'format':'RGBA5551','file':str((out/f'{name}.png').relative_to(ROOT)),'sha256':hashlib.sha256(raw).hexdigest(),'translation_status':'unreviewed'})
    (ROOT/'manifests/images-confirmed.json').write_text(json.dumps(images,ensure_ascii=False,indent=2),encoding='utf-8')
    # Research contact sheets only; do not show irrelevant images in the user review.
    contacts=ROOT/'work/research/image-contacts';contacts.mkdir(exist_ok=True)
    for page in range(math.ceil(len(images)/120)):
        batch=images[page*120:(page+1)*120];sheet=Image.new('RGB',(1000,math.ceil(len(batch)/10)*92),'#586068');draw=ImageDraw.Draw(sheet)
        for i,r in enumerate(batch):
            im=Image.open(ROOT/r['file']);im.thumbnail((94,68));x=i%10*100;y=i//10*92;sheet.paste(im,(x+(96-im.width)//2,y),im);draw.text((x,y+70),r['id'][1:9],fill='white')
        sheet.save(contacts/f'{page:02d}.png')
    print('Font glyphs: 1646; self-describing RGBA16 frames:',len(images))

if __name__=='__main__':main()
