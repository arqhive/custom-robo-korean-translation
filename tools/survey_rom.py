"""Local ROM header and preliminary compressed stream inventory.
Compression reference: Zoinkity / jombo23 N64-Tools CustomRoboCompress.cpp.
This scanner is preliminary; valid streams do not by themselves define file usage.
"""
from pathlib import Path
import struct, hashlib, json, re, zlib
ROOT=Path(__file__).resolve().parents[1]

def decode(b,offset):
    total,packed,size=struct.unpack_from('>III',b,offset)
    assert total>=12 and total%4==0 and 4<=packed<=total-8
    assert total-(packed+8)<=4 and size<0x1000000
    end=offset+packed+8;pos=offset+12;out=bytearray(0xfee)
    while len(out)<0xfee+size:
        assert pos<end
        flags=b[pos];pos+=1
        for bit in range(8):
            if len(out)>=0xfee+size:break
            if flags&(1<<bit):
                assert pos<end;out.append(b[pos]);pos+=1
            else:
                assert pos+2<=end
                low,high=b[pos:pos+2];pos+=2
                src=(len(out)&~0xfff)+(low|((high&0xf0)<<4))
                if src>=len(out):src-=0x1000
                assert 0<=src<len(out)
                for i in range((high&15)+3):out.append(out[src+i])
    assert len(out)-0xfee<=size+17
    assert 0<=end-pos<=17
    return bytes(out[0xfee:0xfee+size]),pos-offset

def main():
    b=(ROOT/'Custom Robo (Japan).z64').read_bytes()
    report={'file':'Custom Robo (Japan).z64','size':len(b),'sha256':hashlib.sha256(b).hexdigest(),'sha1':hashlib.sha1(b).hexdigest(),'md5':hashlib.md5(b).hexdigest(),'crc32':f'{zlib.crc32(b):08X}','byte_order':'big endian z64','internal_name':b[32:52].decode().strip(),'game_id':b[59:63].decode(),'revision':b[63],'entry':hex(struct.unpack_from('>I',b,8)[0]),'header_crc':b[16:24].hex()}
    (ROOT/'manifests/edition.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    out=ROOT/'work/extracted/streams';out.mkdir(parents=True,exist_ok=True)
    rows=[];skip=0
    for p in range(0x1000,len(b)-12,4):
        if p<skip:continue
        total,packed,size=struct.unpack_from('>III',b,p)
        if not(12<=total<=0x100000 and total%4==0 and 4<=packed<=total-8 and total-packed-8<=4 and 0<size<=0x400000 and p+total<=len(b)):continue
        try:raw,used=decode(b,p)
        except (AssertionError,IndexError):continue
        name=f'{p:08X}.bin';(out/name).write_bytes(raw)
        rows.append({'offset':p,'offset_hex':hex(p),'stored_size':total,'packed_size':packed,'decoded_size':size,'consumed':used,'sha256':hashlib.sha256(raw).hexdigest(),'file':str((out/name).relative_to(ROOT))})
        skip=p+total
    (ROOT/'manifests/compressed-streams.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print(json.dumps(report));print('streams',len(rows),'decoded',sum(r['decoded_size'] for r in rows))
    for r in rows[:8]:print(r['offset_hex'],r['stored_size'],r['decoded_size'])

if __name__=='__main__':main()
