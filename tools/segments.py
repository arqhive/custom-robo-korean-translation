"""Segment table (ROM 0x4f500, 9 words each) and simple MIPS address-reference scanner."""
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_BIG_ENDIAN
ROOT=Path(__file__).resolve().parents[1]
TABLE=0x4f500

def segments(rom):
    out=[]
    for i in range(10):
        rs,re_,ram,_,text_end,_,data_end,_,bss_end=struct.unpack_from('>9I',rom,TABLE+i*36)
        out.append({'id':i,'rom_start':rs,'rom_end':re_,'ram':ram,'text_end':text_end,'data_end':data_end,'bss_end':bss_end,
                    'data_rom':rs+(text_end-ram)})
    return out

def seg_of_rom(segs,p):
    for s in segs:
        if s['rom_start']<=p<s['rom_end']:return s
    return None

def rom_to_ram(segs,p):
    s=seg_of_rom(segs,p);return s['ram']+p-s['rom_start']

def ram_to_rom(seg,va):
    return seg['rom_start']+va-seg['ram']

def code_refs(rom,seg):
    """Yield (insn_va, kind, target) for lui/addiu|ori|load|store pairs within a basic window."""
    md=Cs(CS_ARCH_MIPS,CS_MODE_MIPS32|CS_MODE_BIG_ENDIAN)
    start=seg['rom_start'];n=seg['text_end']-seg['ram']
    words=struct.unpack_from('>%dI'%(n//4),rom,start)
    hi={}  # reg -> (value, lui_va)
    out=[]
    for k,w in enumerate(words):
        va=seg['ram']+4*k
        op=w>>26;rs=(w>>21)&31;rt=(w>>16)&31;imm=w&0xffff;simm=imm-0x10000 if imm&0x8000 else imm
        if op==0x0f:  # lui
            hi[rt]=(imm<<16,va);continue
        if rs in hi and op in (0x09,0x0d,0x20,0x21,0x23,0x24,0x25,0x28,0x29,0x2b,0x31,0x35,0x39,0x3d):
            base,lva=hi[rs]
            target=(base|imm) if op==0x0d else (base+simm)&0xffffffff
            out.append((va,lva,op,rs,rt,target))
            if op in (0x09,0x0d) and rt!=rs: pass
            if op in (0x09,0x0d,0x20,0x21,0x23,0x24,0x25) and rt==rs: hi.pop(rs,None)
        # crude: control flow resets nothing (pairs usually close)
        if op in (0x09,0x0d,0x20,0x21,0x23,0x24,0x25,0x0f) and rt in hi and not(rs in hi and rt==rs): hi.pop(rt,None)
        if op==0 and (w&0x3f) in (0x21,0x25,0x23,0x20,0x2a,0x2b,0x24,0x00,0x02,0x03,0x04,0x06,0x07):
            rd=(w>>11)&31;hi.pop(rd,None)
    return out
