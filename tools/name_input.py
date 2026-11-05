"""Hangul name entry: jamo grid + 2-beolsik composition on the name buffer.

Glyph codes are fixed: index 0..2349 = KS X 1001 Hangul syllables in order,
2350..2400 = compatibility jamo U+3131..U+3163. index i -> bytes (0x81+i//94, 0xA1+i%94).
The routine replaces the overlay's "append character" block (seg 8, 0x801E48DC) and
works only on the last character of the name buffer, so it needs no state.
"""
import struct
from keystone import Ks, KS_ARCH_MIPS, KS_MODE_MIPS32, KS_MODE_BIG_ENDIAN

KS=[bytes([a,b]).decode('euc_kr') for a in range(0xb0,0xc9) for b in range(0xa1,0xff)]
assert len(KS)==2350
JAMO=[chr(c) for c in range(0x3131,0x3164)]   # 51
JB=len(KS)
BUF=0x80245d48;LEN=0x80245d58;MAXLEN=6
HOOK=0x801e48dc;HOOK_END=0x801e4910
L_LIST='ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
V_LIST='ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ'
T_LIST=' ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ'
VCOMB={('ㅗ','ㅏ'):'ㅘ',('ㅗ','ㅐ'):'ㅙ',('ㅗ','ㅣ'):'ㅚ',('ㅜ','ㅓ'):'ㅝ',('ㅜ','ㅔ'):'ㅞ',('ㅜ','ㅣ'):'ㅟ',('ㅡ','ㅣ'):'ㅢ'}
TCOMB={('ㄱ','ㅅ'):'ㄳ',('ㄴ','ㅈ'):'ㄵ',('ㄴ','ㅎ'):'ㄶ',('ㄹ','ㄱ'):'ㄺ',('ㄹ','ㅁ'):'ㄻ',('ㄹ','ㅂ'):'ㄼ',
       ('ㄹ','ㅅ'):'ㄽ',('ㄹ','ㅌ'):'ㄾ',('ㄹ','ㅍ'):'ㄿ',('ㄹ','ㅎ'):'ㅀ',('ㅂ','ㅅ'):'ㅄ'}
# final consonant -> (final that stays, consonant that moves to the next syllable)
TSPLIT={'ㄳ':('ㄱ','ㅅ'),'ㄵ':('ㄴ','ㅈ'),'ㄶ':('ㄴ','ㅎ'),'ㄺ':('ㄹ','ㄱ'),'ㄻ':('ㄹ','ㅁ'),'ㄼ':('ㄹ','ㅂ'),
        'ㄽ':('ㄹ','ㅅ'),'ㄾ':('ㄹ','ㅌ'),'ㄿ':('ㄹ','ㅍ'),'ㅀ':('ㄹ','ㅎ'),'ㅄ':('ㅂ','ㅅ')}
GRID=('ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍ'
      'ㅎㄲㄸㅃㅆㅉ　　　　　　　'
      'ㅏㅑㅓㅕㅗㅛㅜㅠㅡㅣ　　　'
      'ㅐㅒㅔㅖㅘㅙㅚㅝㅞㅟㅢ　　'
      '　　　　　　　　　　　　　')
assert len(GRID)==65

# Lead bytes 0x8E/0x8F are EUC-JP SS2/SS3 (half-width kana, 3-byte JIS X 0212): never ours.
SKIP_AT=13*94;SKIP=2*94
def idx2ci(i):return i if i<SKIP_AT else i+SKIP
def idx2code(i):c=idx2ci(i);return bytes([0x81+c//94,0xa1+c%94])
def code_of(ch):
    if ch in KS:return idx2code(KS.index(ch))
    if ch in JAMO:return idx2code(JB+JAMO.index(ch))
    return None

# ---------------------------------------------------------------- reference (Python)
def compose_ref(buf,ch):
    """buf: list of str (each a syllable, jamo, or other). Returns new list."""
    buf=list(buf)
    def app(c):
        if len(buf)<MAXLEN:buf.append(c)
    if ch not in JAMO or not buf:app(ch);return buf
    last=buf[-1]
    def enc(L,V,T):
        c=chr(0xac00+L*588+V*28+T);return c if c in KS else None
    if last in KS:
        u=ord(last)-0xac00;L,V,T=u//588,(u%588)//28,u%28
        if ch not in V_LIST:
            if T==0 and ch in T_LIST[1:]:
                r=enc(L,V,T_LIST.index(ch))
                if r:buf[-1]=r;return buf
            elif T and (T_LIST[T],ch) in TCOMB:
                r=enc(L,V,T_LIST.index(TCOMB[(T_LIST[T],ch)]))
                if r:buf[-1]=r;return buf
        else:
            v=V_LIST.index(ch)
            if T==0:
                if (V_LIST[V],ch) in VCOMB:
                    r=enc(L,V_LIST.index(VCOMB[(V_LIST[V],ch)]),0)
                    if r:buf[-1]=r;return buf
            else:
                keep,move=TSPLIT.get(T_LIST[T],(' ',T_LIST[T]))
                if move in L_LIST and len(buf)<MAXLEN:
                    r1=enc(L,V,T_LIST.index(keep));r2=enc(L_LIST.index(move),v,0)
                    if r1 and r2:buf[-1]=r1;buf.append(r2);return buf
    elif last in JAMO:
        if ch in V_LIST and last in L_LIST:
            r=enc(L_LIST.index(last),V_LIST.index(ch),0)
            if r:buf[-1]=r;return buf
        if ch in V_LIST and last in V_LIST and (last,ch) in VCOMB:
            buf[-1]=VCOMB[(last,ch)];return buf
    app(ch);return buf

# ---------------------------------------------------------------- tables
def tables():
    dec=struct.pack('>2350H',*[ord(c)-0xac00 for c in KS])
    enc=[0]*11172
    for i,c in enumerate(KS):enc[ord(c)-0xac00]=i+1
    enc=struct.pack('>11172H',*enc)
    jl=bytes([L_LIST.index(j) if j in L_LIST else 0xff for j in JAMO])
    jv=bytes([V_LIST.index(j) if j in V_LIST else 0xff for j in JAMO])
    jt=bytes([T_LIST.index(j) if j in T_LIST[1:] else 0 for j in JAMO])
    vc=bytearray(21*21)
    for (a,b),r in VCOMB.items():vc[V_LIST.index(a)*21+V_LIST.index(b)]=V_LIST.index(r)+1
    tc=bytearray(28*51)
    for (a,b),r in TCOMB.items():tc[T_LIST.index(a)*51+JAMO.index(b)]=T_LIST.index(r)
    tkeep=bytearray(28);tmove=bytearray([0xff]*28)
    for t in range(1,28):
        keep,move=TSPLIT.get(T_LIST[t],(' ',T_LIST[t]))
        tkeep[t]=T_LIST.index(keep)
        tmove[t]=L_LIST.index(move) if move in L_LIST else 0xff
    vj=bytes([JAMO.index(v) for v in V_LIST])
    return {'dec':dec,'enc':enc,'jl':jl,'jv':jv,'jt':jt,'vc':bytes(vc),'tc':bytes(tc),'tkeep':bytes(tkeep),'tmove':bytes(tmove),'vj':vj}

def module(base):
    """Code + tables placed at RAM address `base`. Returns bytes and entry address."""
    tb=tables();addr={};blob=bytearray()
    code_size=0x400
    off=code_size
    for k in ['dec','enc','jl','jv','jt','vc','tc','tkeep','tmove','vj']:
        addr[k]=base+off;blob+=tb[k];off+=len(tb[k]);off=(off+3)&~3;blob+=bytes((-len(blob))%4)
    A=addr
    asm=f'''
    .set noreorder
    entry:
        # a0 = 16-bit glyph code chosen on the grid
        lui $t8,{BUF>>16}
        ori $t8,$t8,{BUF&0xffff}
        lui $t9,{LEN>>16}
        ori $t9,$t9,{LEN&0xffff}
        lw $t0,0($t9)              # len
        move $v1,$a0                # code to append by default
        # jamo index j = idx(a0)-{JB}
        bal code2idx
        nop
        addiu $t1,$v0,-{JB}
        sltiu $t2,$t1,51
        beqz $t2,append
        nop
        beqz $t0,append
        nop
        # last char
        sll $t2,$t0,1
        addu $t2,$t2,$t8
        lbu $t3,-2($t2)
        lbu $t4,-1($t2)
        sll $t3,$t3,8
        or $a0,$t3,$t4
        bal code2idx
        nop
        move $t2,$v0               # t2 = idx(last)
        # vowel index of input
        li $t3,{A['jv']}
        addu $t3,$t3,$t1
        lbu $t4,0($t3)             # t4 = Vin (0xff if consonant)
        sltiu $t5,$t2,{JB}
        beqz $t5,last_not_syl
        nop
        # ---- last is a syllable: decompose
        li $t5,{A['dec']}
        sll $t6,$t2,1
        addu $t5,$t5,$t6
        lhu $t5,0($t5)             # u
        li $t6,588
        divu $zero,$t5,$t6
        mflo $a1                   # L
        mfhi $t5
        li $t6,28
        divu $zero,$t5,$t6
        mflo $a2                   # V
        mfhi $a3                   # T
        li $t6,255
        bne $t4,$t6,syl_vowel
        nop
        # consonant input
        bnez $a3,syl_cons_T
        nop
        li $t3,{A['jt']}
        addu $t3,$t3,$t1
        lbu $a3,0($t3)
        beqz $a3,append
        nop
        bal enc
        nop
        bnez $v0,replace
        nop
        b append
        nop
    syl_cons_T:
        li $t3,{A['tc']}
        li $t6,51
        multu $a3,$t6
        mflo $t6
        addu $t3,$t3,$t6
        addu $t3,$t3,$t1
        lbu $a3,0($t3)
        beqz $a3,append
        nop
        bal enc
        nop
        bnez $v0,replace
        nop
        b append
        nop
    syl_vowel:
        bnez $a3,syl_vowel_T
        nop
        li $t3,{A['vc']}
        li $t6,21
        multu $a2,$t6
        mflo $t6
        addu $t3,$t3,$t6
        addu $t3,$t3,$t4
        lbu $a2,0($t3)
        beqz $a2,append
        nop
        addiu $a2,$a2,-1
        bal enc
        nop
        bnez $v0,replace
        nop
        b append
        nop
    syl_vowel_T:
        sltiu $t6,$t0,{MAXLEN}
        beqz $t6,append
        nop
        li $t3,{A['tmove']}
        addu $t3,$t3,$a3
        lbu $t7,0($t3)             # L of the consonant that moves on
        li $t6,255
        beq $t7,$t6,append
        nop
        li $t3,{A['tkeep']}
        addu $t3,$t3,$a3
        lbu $t3,0($t3)             # final that stays
        move $t5,$a1
        move $t6,$a2
        move $a1,$t7
        move $a2,$t4
        bal enc                    # new syllable: (moved, Vin, 0)
        move $a3,$zero
        beqz $v0,append
        nop
        move $t2,$v0
        move $a1,$t5
        move $a2,$t6
        bal enc                    # last syllable keeps (L, V, keep)
        move $a3,$t3
        beqz $v0,append
        nop
        sll $t5,$t0,1
        addu $t5,$t5,$t8
        srl $t6,$v0,8
        sb $t6,-2($t5)
        sb $v0,-1($t5)
        move $v1,$t2
        b append
        nop
    last_not_syl:
        addiu $t2,$t2,-{JB}
        sltiu $t5,$t2,51
        beqz $t5,append
        nop
        li $t6,255
        beq $t4,$t6,append          # consonant after lone jamo: just append
        nop
        li $t3,{A['jl']}
        addu $t3,$t3,$t2
        lbu $a1,0($t3)
        beq $a1,$t6,lone_vowels
        nop
        move $a2,$t4
        move $a3,$zero
        bal enc
        nop
        bnez $v0,replace
        nop
        b append
        nop
    lone_vowels:
        li $t3,{A['jv']}
        addu $t3,$t3,$t2
        lbu $a2,0($t3)
        beq $a2,$t6,append
        nop
        li $t3,{A['vc']}
        li $t6,21
        multu $a2,$t6
        mflo $t6
        addu $t3,$t3,$t6
        addu $t3,$t3,$t4
        lbu $a2,0($t3)
        beqz $a2,append
        nop
        li $t3,{A['vj']-1}
        addu $t3,$t3,$a2
        lbu $a0,0($t3)
        addiu $a0,$a0,{JB}
        bal idx2code
        nop
    replace:
        sll $t2,$t0,1
        addu $t2,$t2,$t8
        srl $t3,$v0,8
        sb $t3,-2($t2)
        sb $v0,-1($t2)
        b done
        nop
    append:
        sltiu $t6,$t0,{MAXLEN}
        beqz $t6,done
        nop
        sll $t2,$t0,1
        addu $t2,$t2,$t8
        srl $t3,$v1,8
        sb $t3,0($t2)
        sb $v1,1($t2)
        addiu $t0,$t0,1
        sw $t0,0($t9)
    done:
        lw $ra,0($sp)
        jr $ra
        addiu $sp,$sp,8

    code2idx:                       # a0 code -> v0 index (big value if not ours)
        srl $v0,$a0,8
        andi $v0,$v0,255
        addiu $v0,$v0,-0x81
        sltiu $at,$v0,32
        beqz $at,c2i_bad
        andi $at,$a0,255
        addiu $at,$at,-0xa1
        sltiu $t7,$at,94
        beqz $t7,c2i_bad
        addiu $t7,$v0,-13
        sltiu $t7,$t7,2
        bnez $t7,c2i_bad             # 0x8E/0x8F
        li $t7,94
        multu $v0,$t7
        mflo $v0
        addu $v0,$v0,$at
        sltiu $t7,$v0,{SKIP_AT+SKIP}
        bnez $t7,c2i_done
        nop
        addiu $v0,$v0,-{SKIP}
    c2i_done:
        jr $ra
        nop
    c2i_bad:
        jr $ra
        li $v0,0xffff
    idx2code:                       # a0 index -> v0 code (skipping leads 0x8E/0x8F)
        sltiu $t7,$a0,{SKIP_AT}
        bnez $t7,i2c_low
        nop
        addiu $a0,$a0,{SKIP}
    i2c_low:
        li $t7,94
        divu $zero,$a0,$t7
        mflo $v0
        mfhi $at
        addiu $v0,$v0,0x81
        sll $v0,$v0,8
        addiu $at,$at,0xa1
        jr $ra
        or $v0,$v0,$at
    enc:                            # (a1 L, a2 V, a3 T) -> v0 code or 0; keeps a1..a3
        li $t7,588
        multu $a1,$t7
        mflo $t7
        sll $at,$a2,5
        sll $v0,$a2,2
        subu $at,$at,$v0            # V*28
        addu $t7,$t7,$at
        addu $t7,$t7,$a3
        sll $t7,$t7,1
        li $at,{A['enc']}
        addu $t7,$t7,$at
        lhu $t7,0($t7)
        beqz $t7,enc_none
        nop
        addiu $a0,$t7,-1
        b idx2code
        nop
    enc_none:
        jr $ra
        move $v0,$zero
    '''
    # nested jal clobbers ra: the entry saves ra on the stack (prologue below)
    pro=f'''.set noreorder
        addiu $sp,$sp,-8
        sw $ra,0($sp)
    '''
    k=Ks(KS_ARCH_MIPS,KS_MODE_MIPS32|KS_MODE_BIG_ENDIAN)
    # enc and lone_vowels call idx2code via b/jal; enc is called with jal and branches to idx2code,
    # which returns to enc's caller. lone_vowels calls idx2code with jal then falls to replace.
    code=bytes(k.asm(pro+asm.replace('.set noreorder',''),addr=base)[0])
    assert len(code)<=code_size,len(code)
    for i in range(0,len(code),4):   # keystone may turn 'jal label' into a $gp call: forbid
        w=int.from_bytes(code[i:i+4],'big');assert not((w>>21)&31==28 and w>>26 in (0x23,0x09)),hex(base+i)
    out=bytearray(code+bytes(code_size-len(code)))+blob
    return bytes(out),base

def hook_bytes(entry):
    k=Ks(KS_ARCH_MIPS,KS_MODE_MIPS32|KS_MODE_BIG_ENDIAN)
    h=bytes(k.asm(f'''.set noreorder
        sll $a0,$t0,8
        or $a0,$a0,$a1
        jal {entry}
        nop
        j {HOOK_END}
        nop''',addr=HOOK)[0])
    assert HOOK+len(h)<=HOOK_END
    return h
