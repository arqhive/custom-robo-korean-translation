"""Built ROM: run the font lookup entry on (name, particle) and check the chosen syllable."""
import json,sys
from unicorn import *
from unicorn.mips_const import *
from survey_rom import ROOT
import font_cache,particles

rom=(ROOT/'build'/(sys.argv[1] if len(sys.argv)>1 else 'Custom Robo (Japan) [KO].z64')).read_bytes()
rep=json.loads((ROOT/'manifests/full-build.json').read_text(encoding='utf-8'))
code={k:int(v,16) for k,v in rep['code_mapping'].items()}
b=rep['font']['string_blob']
uc=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_BIG_ENDIAN);uc.mem_map(0,0x400000)
uc.mem_write(0x25c00,rom[0x1000:0x566b0]);uc.mem_write(int(b['ram'],16)&0x1fffffff,rom[b['rom']:b['rom']+b['bytes']])
RET=0x80380000;WIDTH=0x80300000

def look(c):
    """-> ('hook', a0) when passed on to the glyph lookup, ('blank', width) when drawn as nothing."""
    uc.mem_write(WIDTH&0x1fffffff,b'\xff\xff\xff\xff')
    uc.reg_write(UC_MIPS_REG_A0,c);uc.reg_write(UC_MIPS_REG_A1,WIDTH);uc.reg_write(UC_MIPS_REG_RA,RET)
    uc.emu_start(font_cache.LOOKUP,font_cache.HOOK,count=500)
    pc=uc.reg_read(UC_MIPS_REG_PC)
    if pc==font_cache.HOOK:return ('hook',uc.reg_read(UC_MIPS_REG_A0)&0xffff)
    # returned: the blank path
    uc.emu_start(pc,RET,count=50)
    return ('blank',int.from_bytes(uc.mem_read(WIDTH&0x1fffffff,4),'big'),uc.reg_read(UC_MIPS_REG_V0))

pcode={tok:int.from_bytes(bytes.fromhex(rep['code_mapping'][particles.CHAR[tok]]),'big') if False else None for tok,_ in particles.KINDS}
inv={v:k for k,v in code.items()}
fails=0
for name in ['레이','영','철','진','아키라','삼','ㄱ']:
    for k,(tok,sy) in enumerate(particles.KINDS):
        for ch in name:look(code[ch])
        r=look(code[particles.CHAR[tok]])
        want=sy[particles.final_class(name[-1])]
        got=inv.get(r[1]) if r[0]=='hook' else None
        ok=(got==want) if want else (r[0]=='blank' and r[1]==0)
        fails+=not ok
        print(name,tok,'->',got if r[0]=='hook' else f'(빈칸 폭 {r[1]})','OK' if ok else '틀림 (기대 '+str(want)+')')
# an ordinary glyph after a particle still passes through unchanged
print('보통 글자',look(code['가'])==('hook',code['가']))
print('틀린 수',fails)
