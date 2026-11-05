"""Built ROM: run the patched strcmp (main segment + boot blob) on translated names vs Japanese."""
import json,sys
from unicorn import *
from unicorn.mips_const import *
from survey_rom import ROOT
import build_full as B
rom=(ROOT/'build'/sys.argv[1]).read_bytes();rep=json.loads((ROOT/'manifests/full-build.json').read_text(encoding='utf-8'))
b=rep['font']['string_blob']
uc=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_BIG_ENDIAN);uc.mem_map(0,0x400000)
uc.mem_write(0x25c00,rom[0x1000:0x566b0]);uc.mem_write(int(b['ram'],16)&0x1fffffff,rom[b['rom']:b['rom']+b['bytes']])
B.GLYPHS.update({k:bytes.fromhex(v) for k,v in rep['code_mapping'].items()})
def cmp(x,y):
    uc.mem_write(0x300000,x+b'\0');uc.mem_write(0x301000,y+b'\0')
    uc.reg_write(UC_MIPS_REG_A0,0x80300000);uc.reg_write(UC_MIPS_REG_A1,0x80301000);uc.reg_write(UC_MIPS_REG_RA,0x80380000)
    uc.emu_start(0x8005f4d0,0x80380000,count=100000);return uc.reg_read(UC_MIPS_REG_V0)
disp=B.load_raw();ok=bad=0
for p,r in disp.items():
    if r['translation'] is None or r['source'][:1] in 'ZMNIHKL':continue
    ko=B.enc_seg(r['translation'],False);jp=r['source'].encode('euc_jp')
    if ko==jp:continue
    if cmp(ko,jp)==0 and cmp(jp,ko)==0 and cmp(ko,ko)==0:ok+=1
    else:bad+=1
print('translated names equal to their Japanese original under strcmp:',ok,'failed',bad)
print('different names still differ:',cmp(B.enc_seg('레이',False),'ソル'.encode('euc_jp'))!=0)
