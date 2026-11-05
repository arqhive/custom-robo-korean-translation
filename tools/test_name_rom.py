"""Run the built ROM's own hook (seg 8) + RAM-blob routine on the CPU emulator (no game, no input)."""
import json,struct,sys
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS32,UC_MODE_BIG_ENDIAN
from unicorn.mips_const import *
from segments import segments
import name_input as N
from survey_rom import ROOT
rom=(ROOT/'build'/sys.argv[1]).read_bytes();rep=json.loads((ROOT/'manifests/full-build.json').read_text(encoding='utf-8'))
S=segments(rom);s8=S[8];b=rep['font']['string_blob']
uc=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_BIG_ENDIAN)
uc.mem_map(0,0x400000)
uc.mem_write(s8['ram']&0x1fffffff,rom[s8['rom_start']:s8['rom_end']])          # overlay 8 as loaded
uc.mem_write(int(b['ram'],16)&0x1fffffff,rom[b['rom']:b['rom']+b['bytes']])    # boot-time DMA of the blob
grid=rom[0x114fc0:0x114fc0+130]
rev={N.code_of(c):c for c in N.KS+N.JAMO}
def press(cell):
    code=grid[2*cell:2*cell+2]
    uc.reg_write(UC_MIPS_REG_T0,code[0]);uc.reg_write(UC_MIPS_REG_A1,code[1])
    uc.reg_write(UC_MIPS_REG_SP,0x803f0000)
    uc.emu_start(N.HOOK,0x801e4910,count=5000)
    assert uc.reg_read(UC_MIPS_REG_PC)==0x801e4910,hex(uc.reg_read(UC_MIPS_REG_PC))
def name():
    n=struct.unpack('>I',uc.mem_read(N.LEN&0x1fffffff,4))[0];raw=bytes(uc.mem_read(N.BUF&0x1fffffff,2*n))
    return ''.join(rev.get(raw[i:i+2]) or raw[i:i+2].decode('euc_jp') for i in range(0,len(raw),2))
G=N.GRID
for word in ['ㅎㅏㅇㅑㅌㅗ','ㄱㅣㅁㅊㅓㄹㅅㅜ','ㅇㅗㅏㄴㄷㅡㄹ']:
    uc.mem_write(N.LEN&0x1fffffff,bytes(4))
    for ch in word:press(G.index(ch))
    print(word,'->',name(),'(ref',''.join(N.compose_ref.__call__([], '') if False else ''.join(__import__('functools').reduce(N.compose_ref,word,[]))),')')
