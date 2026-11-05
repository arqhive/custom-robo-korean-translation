"""Korean particles after the player's name: 을/를, 이/가 ... chosen at draw time.

Translations write a particle as {을/를}; the build turns each kind into a spare glyph code.
The font lookup entry first runs this module (in the RAM string blob): it remembers the last
glyph code drawn, and when a particle code comes it looks up that glyph's final consonant
(0 none or not Hangul, 1 a final other than ㄹ, 2 ㄹ) and passes the matching syllable on to
the normal lookup. An optional syllable ({이}, {으}) with no match is a blank glyph of width 0.
"""
import struct
from keystone import Ks, KS_ARCH_MIPS, KS_MODE_MIPS32, KS_MODE_BIG_ENDIAN

# token -> syllable for (no final, final other than ㄹ, final ㄹ); None = nothing (width 0)
KINDS=[('{을/를}',('를','을','을')),('{이/가}',('가','이','이')),('{은/는}',('는','은','은')),
       ('{과/와}',('와','과','과')),('{아/야}',('야','아','아')),('{이}',(None,'이','이')),
       ('{으}',(None,'으',None)),('{에/예}',('예','에','에'))]
CHAR={tok:chr(0xE000+k) for k,(tok,_) in enumerate(KINDS)}   # private-use stand-ins inside the build

def to_chars(t):
    for tok,c in CHAR.items():t=t.replace(tok,c)
    return t

def final_class(ch):
    if not '가'<=ch<='힣':return 0
    f=(ord(ch)-0xAC00)%28
    return 0 if f==0 else 2 if f==8 else 1

def ci(code):return (code[0]-0x81)*94+code[1]-0xa1

def module(va,glyph_codes,particle_codes,lookup_hook,blank_texture):
    """glyph_codes: char -> 2-byte code of every Korean glyph; particle_codes: kind index -> code.
    Returns (bytes, entry VA)."""
    pci=[ci(c) for c in particle_codes]
    assert pci==list(range(pci[0],pci[0]+len(KINDS))),'particle codes must be consecutive'
    n=max(ci(c) for c in glyph_codes.values())+1
    cls=bytearray(n)
    for ch,c in glyph_codes.items():cls[ci(c)]=final_class(ch)
    pairs=b''.join(struct.pack('>3H',*[(int.from_bytes(glyph_codes[s],'big') if s else 0) for s in sy]) for _,sy in KINDS)
    PREV=va;PAIRS=va+4;CLASS=PAIRS+len(pairs);code_va=(CLASS+n+3)&~3
    k=Ks(KS_ARCH_MIPS,KS_MODE_MIPS32|KS_MODE_BIG_ENDIAN)
    code=bytes(k.asm(f'''.set noreorder
        andi $a0,$a0,65535
        srl $t0,$a0,8
        addiu $t0,$t0,-129
        sltiu $t1,$t0,32
        beqz $t1,normal
        andi $t1,$a0,255
        addiu $t1,$t1,-161
        sltiu $t2,$t1,94
        beqz $t2,normal
        li $t2,94
        multu $t0,$t2
        mflo $t0
        addu $t0,$t0,$t1
        addiu $t2,$t0,-{pci[0]}
        sltiu $t3,$t2,{len(KINDS)}
        bnez $t3,particle
        nop
    normal:
        li $t9,{PREV}
        sw $a0,0($t9)
        j {lookup_hook}
        nop
    particle:
        li $t9,{PREV}
        lw $t3,0($t9)
        move $t4,$zero
        srl $t5,$t3,8
        addiu $t5,$t5,-129
        sltiu $t6,$t5,32
        beqz $t6,pick
        andi $t6,$t3,255
        addiu $t6,$t6,-161
        sltiu $t7,$t6,94
        beqz $t7,pick
        li $t7,94
        multu $t5,$t7
        mflo $t5
        addu $t5,$t5,$t6
        sltiu $t6,$t5,{n}
        beqz $t6,pick
        li $t6,{CLASS}
        addu $t6,$t6,$t5
        lbu $t4,0($t6)
    pick:
        sll $t5,$t2,1
        addu $t5,$t5,$t2
        addu $t5,$t5,$t4
        sll $t5,$t5,1
        li $t6,{PAIRS}
        addu $t6,$t6,$t5
        lhu $a0,0($t6)
        beqz $a0,blank
        nop
        j {lookup_hook}
        nop
    blank:
        li $v0,{blank_texture}
        jr $ra
        sw $zero,0($a1)
    ''',addr=code_va)[0])
    out=bytes(4)+pairs+bytes(cls)
    out+=bytes(code_va-va-len(out))+code
    return out,code_va
