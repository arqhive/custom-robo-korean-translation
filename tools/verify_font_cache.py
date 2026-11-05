"""Exercise the generated MIPS hook with cache misses, hits, wraps and Japanese."""
import json,random,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS32,UC_MODE_BIG_ENDIAN,UC_HOOK_CODE,UC_HOOK_MEM_READ
from unicorn.mips_const import *
from font_cache import INIT,LOOKUP,TEXTURES,KEYS,CURSOR,SLOT_INDICES,SLOTS
ROOT=Path(__file__).resolve().parents[1]

def main():
    report=json.loads((ROOT/'manifests/scenario-build.json').read_text(encoding='utf-8'))
    rom=(ROOT/report['file']).read_bytes()
    uc=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_BIG_ENDIAN);uc.mem_map(0,0x400000)
    uc.mem_map(0x10000000,len(rom));uc.mem_write(0x10000000,rom)
    uc.mem_write(0x25c00,rom[0x1000:0x566b0]);transfers=[];cartridge_reads=[]
    def cartridge(u,access,address,size,value,data):cartridge_reads.append(address)
    uc.hook_add(UC_HOOK_MEM_READ,cartridge,begin=0x10000000,end=0x10ffffff)
    def service(u,address,size,data):
        if address==0x8003bffc:
            src=u.reg_read(UC_MIPS_REG_A0);dst=u.reg_read(UC_MIPS_REG_A1)&0x1fffffff;n=u.reg_read(UC_MIPS_REG_A2)
            assert src+n<=len(rom) and dst+n<=0x400000
            u.mem_write(dst,rom[src:src+n]);transfers.append((src,dst,n))
        u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
    for addr in [0x8003bffc,0x8004be30]:uc.hook_add(UC_HOOK_CODE,service,begin=addr,end=addr)
    def run(addr):
        uc.reg_write(UC_MIPS_REG_SP,0x803f0000);uc.reg_write(UC_MIPS_REG_RA,0x80001000)
        uc.emu_start(addr,0x80001000,count=100000)
        assert uc.reg_read(UC_MIPS_REG_PC)==0x80001000
        assert uc.reg_read(UC_MIPS_REG_SP)==0x803f0000
    run(INIT)
    n=1647*96;p=report['original_texture_rom']
    assert bytes(uc.mem_read(TEXTURES&0x1fffffff,n))==rom[p:p+n]
    assert bytes(uc.mem_read(KEYS&0x1fffffff,408))==bytes(408)
    # The real game overwrites its old font source buffer with stage data.
    # Poison that exact region before every lookup regression test.
    uc.mem_write(0x7b858,b'\x61'*0x73bc)
    count=report['glyph_count'];ko=list(report['code_mapping'].values())
    japan=json.loads((ROOT/'manifests/font.json').read_text(encoding='utf-8'))
    order=list(range(count));random.Random(47).shuffle(order)
    preserved=[i for i in range(len(japan)) if i not in SLOT_INDICES]
    tests=[('ko',i) for i in range(count)]+[('ko',i) for i in order]+[('jp',i) for i in preserved]
    tests += [('ko',i) for i in range(min(count,81))]*4
    for typ,i in tests:
        code=int(ko[i],16) if typ=='ko' else int(japan[i]['euc_jp'],16)
        uc.reg_write(UC_MIPS_REG_A0,code);uc.reg_write(UC_MIPS_REG_A1,0x803e0000)
        run(LOOKUP)
        ptr=uc.reg_read(UC_MIPS_REG_V0)&0x1fffffff
        if typ=='ko':
            assert ptr in {(TEXTURES&0x1fffffff)+idx*96 for idx in SLOT_INDICES}
            p=report['korean_texture_rom']+i*96;width=12
        else:p=report['original_texture_rom']+i*96;width=japan[i]['advance']
        assert bytes(uc.mem_read(ptr,96))==rom[p:p+96],(typ,i,hex(code))
        assert struct.unpack('>I',uc.mem_read(0x3e0000,4))[0]==width
    # A stable dialogue-sized working set produces no further ROM transfers.
    before=len(cartridge_reads)
    assert before>0
    for i in range(81):
        uc.reg_write(UC_MIPS_REG_A0,int(ko[i],16));uc.reg_write(UC_MIPS_REG_A1,0x803e0000);run(LOOKUP)
    assert len(cartridge_reads)==before
    result={'mips_lookup_checks':len(tests)+81,'glyphs':count,'japanese_glyphs_checked':len(preserved),
            'cache_wrap_checked':True,'stable_81_glyph_working_set_no_cartridge_reads':True,'ram_bytes_mapped':0x400000,
            'old_font_source_buffer_overwrite_safe':True,
            'emulator_gameplay_test':False}
    (ROOT/'manifests/font-cache-validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
