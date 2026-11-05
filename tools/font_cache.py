"""Korean glyph cache inside font texture slots absent from the text inventory.

The original font source buffer is reused by the game after initialization;
it MUST NOT hold persistent cache data. Metadata lives in the replaced font
initializer's own RAM, and textures reuse unused CJK texture slots.
"""
from pathlib import Path
import struct,json
import numpy as np
from keystone import Ks, KS_ARCH_MIPS, KS_MODE_MIPS32, KS_MODE_BIG_ENDIAN
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_BIG_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import UC_MIPS_REG_SP, UC_MIPS_REG_RA, UC_MIPS_REG_PC, UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2
from unicorn.mips_const import UC_MIPS_REG_A3, UC_MIPS_REG_V0, UC_MIPS_REG_V1

INIT=0x8002c250
LOOKUP=0x8002caa0
HOOK=0x8002c300
FALLBACK=0x8002c600
TEXTURES=0x800dc7b0
KEYS=0x8002c640
CURSOR=KEYS+404
SLOT_TABLE=0x8002c800
ROOT=Path(__file__).resolve().parents[1]
SLOT_INDICES=[r['index'] for r in json.loads((ROOT/'manifests/font-unused-candidates.json').read_text(encoding='utf-8')) if '\u4e00'<=r['char']<='\u9fff']
SLOTS=len(SLOT_INDICES)
assert SLOTS==201 and SLOT_TABLE+SLOTS*2<=0x8002ca68

def asm(code,address):
    # No assembler-inserted delay slots: every branch/jump has an explicit slot.
    k=Ks(KS_ARCH_MIPS,KS_MODE_MIPS32|KS_MODE_BIG_ENDIAN)
    return bytes(k.asm('.set noreorder\n'+code,addr=address)[0])

def expand(bits):
    a=np.unpackbits(np.frombuffer(bits,dtype=np.uint8)).reshape(12,12)
    out=np.zeros((13,16),dtype=np.uint8)
    out[:12,:12]=a*15
    out[:12,1:13]|=a*3
    out[1:13,:12]|=a*3
    out[1:13,1:13]|=a*3
    flat=out[:12].reshape(-1)
    return ((flat[::2]<<4)|flat[1::2]).tobytes()

def original_expanded(rom):
    """Execute the original game's font initializer as an independent oracle."""
    uc=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_BIG_ENDIAN)
    uc.mem_map(0,0x400000)
    uc.mem_write(0x25c00,rom[0x1000:0x566b0])
    uc.reg_write(UC_MIPS_REG_SP,0x803f0000)
    uc.reg_write(UC_MIPS_REG_RA,0x80001000)
    def service(u,address,size,data):
        if address==0x8003bffc:
            src=u.reg_read(UC_MIPS_REG_A0);dst=u.reg_read(UC_MIPS_REG_A1)&0x1fffffff;n=u.reg_read(UC_MIPS_REG_A2)
            u.mem_write(dst,rom[src:src+n]);u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
        elif address==0x8004be30:u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
        elif address in (0x80052384,0x800522e0):
            # These two leaf helpers use MIPS64 dsllv/dsrlv; supply their exact
            # pair-register arithmetic to the MIPS32-only test CPU.
            value=(u.reg_read(UC_MIPS_REG_A0)<<32)|u.reg_read(UC_MIPS_REG_A1)
            shift=u.reg_read(UC_MIPS_REG_A3)&63
            result=(value<<shift)&0xffffffffffffffff if address==0x80052384 else value>>shift
            u.reg_write(UC_MIPS_REG_V0,result>>32);u.reg_write(UC_MIPS_REG_V1,result&0xffffffff)
            u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
    uc.hook_add(UC_HOOK_CODE,service,begin=0x8003bffc,end=0x8003bffc)
    uc.hook_add(UC_HOOK_CODE,service,begin=0x8004be30,end=0x8004be30)
    uc.hook_add(UC_HOOK_CODE,service,begin=0x80052384,end=0x80052384)
    uc.hook_add(UC_HOOK_CODE,service,begin=0x800522e0,end=0x800522e0)
    uc.emu_start(INIT,0x80001000,count=20000000)
    assert uc.reg_read(UC_MIPS_REG_PC)==0x80001000
    result=bytes(uc.mem_read(TEXTURES&0x1fffffff,1647*96))
    expected=b''.join(expand(rom[p:p+18]) for p in range(0x1195a0,0x12095c,18))+b'\xff'*96
    assert expected==result,'Offline expansion differs from original N64 font initializer'
    return result

def patch(rom,original_texture_rom,korean_texture_rom,glyph_count):
    def put(va,data):rom[va-0x80024c00:va-0x80024c00+len(data)]=data
    # Replace only the old initializer body. Original lookup/comparator remain.
    put(INIT,bytes(0x8002ca68-INIT))
    put(SLOT_TABLE,struct.pack('>'+str(SLOTS)+'H',*SLOT_INDICES))
    init=asm(f'''
        addiu $sp,$sp,-32
        sw $ra,28($sp)
        jal 0x8004be30
        nop
        li $a0,{original_texture_rom}
        li $a1,{TEXTURES}
        li $a2,{1647*96}
        jal 0x8003bffc
        nop
        li $t0,{KEYS}
        li $t1,{CURSOR+4}
    clear:
        sw $zero,0($t0)
        addiu $t0,$t0,4
        bne $t0,$t1,clear
        nop
        lw $ra,28($sp)
        addiu $sp,$sp,32
        jr $ra
        nop
    ''',INIT)
    assert INIT+len(init)<=HOOK
    put(INIT,init)
    hook=asm(f'''
        andi $a0,$a0,65535
        srl $t0,$a0,8
        addiu $t0,$t0,-129
        sltiu $t1,$t0,32
        beqz $t1,original
        nop
        addiu $t1,$t0,-13
        sltiu $t1,$t1,2
        bnez $t1,original              # 0x8E/0x8F: EUC-JP SS2/SS3, keep the original font path
        nop
        andi $t1,$a0,255
        addiu $t1,$t1,-161
        sltiu $t2,$t1,94
        beqz $t2,original
        nop
        li $t2,94
        multu $t0,$t2
        mflo $t0
        addu $t0,$t0,$t1
        sltiu $t2,$t0,{glyph_count}
        beqz $t2,original
        nop
        li $t1,{KEYS}
        move $t2,$zero
    search:
        lhu $t3,0($t1)
        beq $t3,$a0,hit
        nop
        addiu $t2,$t2,1
        sltiu $t3,$t2,{SLOTS}
        bnez $t3,search
        addiu $t1,$t1,2
        li $t1,{CURSOR}
        lw $t2,0($t1)
        addiu $t3,$t2,1
        sltiu $t4,$t3,{SLOTS}
        bnez $t4,store_cursor
        nop
        move $t3,$zero
    store_cursor:
        sw $t3,0($t1)
        li $t3,{KEYS}
        sll $t4,$t2,1
        addu $t3,$t3,$t4
        sh $a0,0($t3)
        li $t3,{SLOT_TABLE}
        sll $t4,$t2,1
        addu $t3,$t3,$t4
        lhu $t2,0($t3)
        sll $t3,$t2,6
        sll $t4,$t2,5
        addu $t3,$t3,$t4
        li $t4,{TEXTURES}
        addu $t3,$t3,$t4
        sll $t1,$t0,6
        sll $t2,$t0,5
        addu $t0,$t1,$t2
        li $t1,{0xb0000000+korean_texture_rom}
        addu $t1,$t1,$t0
        move $v0,$t3
        addiu $t4,$t3,96
    invalidate:
        cache 17,0($t3)
        addiu $t3,$t3,16
        bne $t3,$t4,invalidate
        nop
        li $t4,0x20000000
        or $t3,$v0,$t4
        addiu $t4,$t3,96
    copy:
        lw $t5,0($t1)
        sw $t5,0($t3)
        addiu $t1,$t1,4
        addiu $t3,$t3,4
        bne $t3,$t4,copy
        nop
        li $t0,12
        sw $t0,0($a1)
        jr $ra
        nop
    hit:
        li $t3,{SLOT_TABLE}
        sll $t4,$t2,1
        addu $t3,$t3,$t4
        lhu $t2,0($t3)
        sll $t3,$t2,6
        sll $t4,$t2,5
        addu $t3,$t3,$t4
        li $v0,{TEXTURES}
        addu $v0,$v0,$t3
        li $t0,12
        sw $t0,0($a1)
        jr $ra
        nop
    original:
        j {FALLBACK}
        nop
    ''',HOOK)
    assert HOOK+len(hook)<=FALLBACK
    put(HOOK,hook)
    put(FALLBACK,asm('addiu $sp,$sp,-32\nsw $a1,36($sp)\nj 0x8002caa8\nnop',FALLBACK))
    put(LOOKUP,asm(f'j {HOOK}\nnop',LOOKUP))
    return {'cache_slots':SLOTS,'cache_metadata_start':hex(KEYS),'cache_metadata_end':hex(CURSOR+4),
            'cache_texture_indices':SLOT_INDICES,
            'japanese_glyphs_preserved':1646-SLOTS,'unused_cjk_slots_repurposed':SLOTS,'expansion_pak_required':False,
            'cache_fill':'Uncached cartridge word reads and uncached RDRAM writes; no blocking DMA in lookup',
            'hook_code_bytes':len(hook),'initializer_bytes':len(init),
            'limitation':'Cache uses 201 CJK slots absent from extracted text; full gameplay coverage and persistent UI use need further validation.'}

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    original=(root/'Custom Robo (Japan).z64').read_bytes()
    textures=original_expanded(original)
    (root/'work/research/original-font-i4.bin').write_bytes(textures)
    print('All 1646 original glyphs and fallback match original initializer byte for byte.')
