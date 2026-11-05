"""CPU-level test of the name composition routine against the Python reference (unicorn)."""
import random,struct,sys
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS32,UC_MODE_BIG_ENDIAN
from unicorn.mips_const import *
import name_input as N
BASE=0x802e22a0
mod,entry=N.module(BASE)
def run(seq):
    uc=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_BIG_ENDIAN)
    uc.mem_map(0x00200000,0x200000)
    uc.mem_write(BASE&0x1fffffff,mod)
    buf=[]
    for ch in seq:
        code=N.code_of(ch) or ch.encode('euc_jp')
        uc.reg_write(UC_MIPS_REG_A0,int.from_bytes(code,'big'))
        uc.reg_write(UC_MIPS_REG_SP,0x803f0000)
        uc.reg_write(UC_MIPS_REG_RA,0x80300000)
        uc.emu_start(entry,0x80300000,count=5000)
        assert uc.reg_read(UC_MIPS_REG_PC)==0x80300000
    n=struct.unpack('>I',uc.mem_read(N.LEN&0x1fffffff,4))[0]
    raw=bytes(uc.mem_read(N.BUF&0x1fffffff,2*n))
    rev={N.code_of(c):c for c in N.KS+N.JAMO}
    return [rev.get(raw[i:i+2]) or raw[i:i+2].decode('euc_jp') for i in range(0,len(raw),2)]
def ref(seq):
    b=[]
    for ch in seq:b=N.compose_ref(b,ch)
    return b
cases=['ㅎㅏㅇㅑㅌㅗ','ㄱㅏㅂㅅ','ㄱㅏㅂㅅㅣ','ㄷㅏㄹㄱㅏ','ㅇㅗㅏ','ㅁㅜㅓㅅ','ㅇㅡㅣㅅㅏ','ㅅㅏㄹㅁ','ㅏㅣ','ㅗㅏ','ㄲㅗㅊ','ㄱㅣㅁㅊㅣ','ㅍㅏㄹㅂㅏㅇ','ㄴㅏㅎㅇㅏ','あいㄱㅏ','ㅂㅂㅂㅂㅂㅂㅂㅂ','ㄱㅏㄱㅏㄱㅏㄱㅏㄱㅏㄱㅏㄴ','ㄱㅏㄱㅏㄱㅏㄱㅏㄱㅏㄱㅏㄱㅏ','ㅆㅑㄹ']
bad=0
for c in cases:
    a,b=run(c),ref(c)
    print(c,'->',''.join(a),'' if a==b else ' REF '+''.join(b));bad+=a!=b
random.seed(1);pool=N.JAMO[:30]+list('ㅏㅑㅓㅕㅗㅛㅜㅠㅡㅣㅐㅒㅔㅖ')*2+['あ']
for i in range(3000):
    seq=[random.choice(pool) for _ in range(random.randint(1,12))]
    if run(seq)!=ref(seq):bad+=1;print('MISMATCH',''.join(seq),run(seq),ref(seq)) if bad<10 else None
print('mismatches',bad)
