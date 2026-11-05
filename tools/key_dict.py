"""Translated names stay comparable: strcmp (0x8005F4D0) maps a Korean string back to its
Japanese original before comparing.

The game finds parts, stages, backgrounds and more by comparing names with strcmp
against untranslated tables, battle definitions and asset headers. Display strings
are translated in memory, so every strcmp argument that starts with one of our Hangul
lead bytes is looked up in an open-addressing table
(hash of the Korean bytes -> Japanese bytes) placed in the RAM blob.
"""
import struct
from keystone import Ks, KS_ARCH_MIPS, KS_MODE_MIPS32, KS_MODE_BIG_ENDIAN

STRCMP=0x8005f4d0

def h31(b):
    h=0
    for c in b:h=(h*31+c)&0xffffffff
    return h

CODE_VA=0x8002c4a0;CODE_END=0x8002c600   # free tail of the replaced font initializer (main segment)

def table(base,pairs):
    """Hash table + strings placed at RAM `base` (inside the boot blob)."""
    size=1
    while size<len(pairs)*2:size*=2
    mask=size-1;code_size=0
    strings=bytearray();tab=[(0,0)]*size
    def put(b):
        nonlocal strings
        o=len(strings);strings+=b+b'\0';return o
    soff=code_size+size*8
    placed=[]
    for ko,jp in pairs:
        k=put(ko);j=put(jp);placed.append((ko,k,j))
    for ko,k,j in placed:
        i=h31(ko)&mask
        while tab[i][0]:i=(i+1)&mask
        tab[i]=(base+soff+k,base+soff+j)
    out=bytearray()
    for a,b in tab:out+=struct.pack('>II',a,b)
    out+=strings
    return bytes(out),base,mask

def code(TAB,mask):
    asm=f'''.set noreorder
    entry:
        move $t8,$ra
        bal map
        move $t9,$a0
        move $a0,$v0
        bal map
        move $t9,$a1
        move $a1,$v0
        move $ra,$t8
    cmp:                            # the original strcmp
        lbu $v0,0($a0)
    cloop:
        lbu $v1,0($a1)
        addiu $a0,$a0,1
        addiu $a1,$a1,1
        beq $v1,$v0,ceq
        move $a3,$v0
        jr $ra
        subu $v0,$a3,$v1
    ceq:
        bnel $v0,$zero,cloop
        lbu $v0,0($a0)
        jr $ra
        move $v0,$zero

    map:                            # t9 = string -> v0 = Japanese original or t9
        move $v0,$t9
        move $t2,$zero               # hash (every argument: names may start with any glyph)
        move $t3,$t9
    hloop:
        lbu $t0,0($t3)
        beqz $t0,hdone
        sll $t1,$t2,5
        subu $t2,$t1,$t2             # h*31
        addu $t2,$t2,$t0
        b hloop
        addiu $t3,$t3,1
    hdone:
        andi $t2,$t2,{mask}
        lui $t4,{TAB>>16}
        ori $t4,$t4,{TAB&0xffff}
    probe:
        sll $t1,$t2,3
        addu $t1,$t1,$t4
        lw $t5,0($t1)                # korean ptr
        beqz $t5,mret
        move $t6,$t9
    sloop:
        lbu $t0,0($t6)
        lbu $t7,0($t5)
        bne $t0,$t7,snext
        addiu $t6,$t6,1
        bnez $t0,sloop
        addiu $t5,$t5,1
        jr $ra                       # equal: return Japanese ptr
        lw $v0,4($t1)
    snext:
        addiu $t2,$t2,1
        b probe
        andi $t2,$t2,{mask}
    mret:
        jr $ra
        nop
    '''
    k=Ks(KS_ARCH_MIPS,KS_MODE_MIPS32|KS_MODE_BIG_ENDIAN)
    c=bytes(k.asm(asm,addr=CODE_VA)[0])
    assert CODE_VA+len(c)<=CODE_END,len(c)
    for i in range(0,len(c),4):
        w=int.from_bytes(c[i:i+4],'big');assert not((w>>21)&31==28 and w>>26 in (0x23,0x09)),hex(CODE_VA+i)
    return c

def hook_bytes(entry):
    k=Ks(KS_ARCH_MIPS,KS_MODE_MIPS32|KS_MODE_BIG_ENDIAN)
    return bytes(k.asm(f'''.set noreorder
        j {entry}
        nop''',addr=STRCMP)[0])
