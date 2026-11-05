"""CPU test: hooked strcmp equals strcmp of the Japanese originals (unicorn)."""
import random
from unicorn import *
from unicorn.mips_const import *
import key_dict as K
pairs=[('레이'.encode('euc_kr'),'レイ'.encode('euc_jp')),('스테이지'.encode('euc_kr'),'ステージ'.encode('euc_jp'))]
# our codes are not EUC-KR; emulate with lead 0x81.. bytes
def kor(i,n):return bytes([0x81+(i%25),0xa1+(i*7%94)])*n
pairs=[(kor(i,1+i%6)+bytes([0x81+i%25,0xa1+i%94]),('名'*(1+i%5)+str(i)).encode('euc_jp')) for i in range(800)]
pairs=list({k:v for k,v in pairs}.items())
BASE=0x802e8000
tab,base,mask=K.table(BASE,pairs);code=K.code(BASE,mask)
uc=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_BIG_ENDIAN);uc.mem_map(0,0x400000)
uc.mem_write(BASE&0x1fffffff,tab);uc.mem_write(K.CODE_VA&0x1fffffff,code)
A=0x00300000;B=0x00301000
def cmp(x,y):
    uc.mem_write(A,x+b'\0');uc.mem_write(B,y+b'\0')
    uc.reg_write(UC_MIPS_REG_A0,0x80000000|A);uc.reg_write(UC_MIPS_REG_A1,0x80000000|B);uc.reg_write(UC_MIPS_REG_RA,0x80380000)
    uc.emu_start(K.CODE_VA,0x80380000,count=100000)
    v=uc.reg_read(UC_MIPS_REG_V0);return 0 if v==0 else (1 if v<0x80000000 else -1)
J=dict(pairs)
def ref(x,y):
    x=J.get(x,x);y=J.get(y,y)
    for a,b in zip(x+b'\0',y+b'\0'):
        if a!=b:return 1 if a>b else -1
        if a==0:return 0
    return 0
random.seed(2);bad=0;n=0
keys=list(J);jps=list(J.values())
for _ in range(3000):
    x=random.choice([random.choice(keys),random.choice(jps),b'\xa5\xec\xa5\xa4',kor(999,3)])
    y=random.choice([random.choice(keys),random.choice(jps),J[x] if x in J else x])
    n+=1;bad+=cmp(x,y)!=ref(x,y)
print('cases',n,'mismatch',bad,'table bytes',len(tab),'code',len(code))
# zero table (before the boot DMA): must behave as plain strcmp
uc.mem_write(BASE&0x1fffffff,bytes(len(tab)))
print('zero-table',[cmp(a,b) for a,b in [(keys[0],jps[0]),(jps[0],jps[0]),(b'abc',b'abd')]])
