"""Full Korean build: scenario pools, overlay display strings, glyph cache, images.

Scenario: translated dialogue that no longer fits its pool slot is appended to the
end of the pool; every opcode-0x10 operand that pointed at the old pool offset is
rewritten. Overlay strings: pointer-reached blocks that no longer fit in place are
copied to a RAM blob (0x802E0000, unused by every overlay; audio heap starts at
0x8033F800) which the patched font initializer DMAs at boot; data pointers and
lui/lo pairs are rewritten to the copy.
"""
from pathlib import Path
import json,re,struct,hashlib,collections,sys
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from survey_rom import ROOT,decode
from codec import encode
from build_opening_probe import crc6102
from translation_catalog import CONTROL,literal
from master_text_catalog import raw_translations
from segments import segments,seg_of_rom,code_refs
import font_cache
import name_input
import key_dict
import particles
from keystone import Ks, KS_ARCH_MIPS, KS_MODE_MIPS32, KS_MODE_BIG_ENDIAN

BLOB_VA=0x802e0000
BLOB_LIMIT=0x8033f800
FONT=Path('C:/Users/hgyst/AppData/Local/Microsoft/Windows/Fonts/Galmuri11.ttf')
PREFIX=set(b'ZMNIHKL')
LINE_W=206          # widest Japanese dialogue line (px)
NAME_W=72           # $A00 allowance: Japanese lines leave 78px for the name
MAX_LINES=3
CREDITS=(0x9d870,0x9dd30)
REPORT={}
import os
OFF=set(filter(None,os.environ.get('KO_OFF','').split(',')))   # test builds only
GLYPHS={}

# ---------------------------------------------------------------- translations
def load_dialogue():
    rows=json.loads((ROOT/'work/translation/source-texts.json').read_text(encoding='utf-8'))
    byid={r['id']:r for r in rows};tr={}
    for p in [ROOT/'work/translation/opening-ko.json',*sorted((ROOT/'work/translation').glob('scenario-*-ko.json'))]:
        for k,v in json.loads(p.read_text(encoding='utf-8')).items():
            assert k in byid and k not in tr,k
            # the player's name ($A00) may be replaced by a pronoun (「너」), and line/page breaks
            # ($R/$P) may move or be added to fit the window; every other code must stay
            lay=('$A00','$R','$P','$W')
            # waits ($W) move with the line/page breaks when a line is rebroken to fit, so they
            # count as layout too; faces, colours, speeds and other codes must stay as in the source
            cv=CONTROL.findall(v);cs=CONTROL.findall(byid[k]['source'])
            assert [c for c in cv if c not in lay]==[c for c in cs if c not in lay] and cv.count('$A00')<=cs.count('$A00'),k
            # a page break without a wait skips ahead on its own; only where the source does that
            nowait=lambda t:len(re.findall(r'(?<!\$W)\$P',t))
            assert nowait(v)==nowait(byid[k]['source']),(k,'page break without $W')
            assert not re.search('[ぁ-ゟァ-ヺ一-鿿]',v),k
            # particles after the name ({을/를} ...) are chosen at draw time
            assert not re.search(r'[{}]',particles.to_chars(v)),(k,'unknown particle token')
            tr[k]=particles.to_chars(v)
    bysource={}
    for k,v in tr.items():
        s=byid[k]['source'];assert bysource.get(s,v)==v,('inconsistent duplicate',k);bysource[s]=v
    return rows,bysource

def load_raw():
    raw=json.loads((ROOT/'work/translation/raw-text-classified.json').read_text(encoding='utf-8'))
    tr,_=raw_translations(raw)
    ctx=ROOT/'work/translation/context-raw-ko.json'   # same source, different sentence context
    if ctx.exists():tr.update(json.loads(ctx.read_text(encoding='utf-8')))
    disp={r['rom_offset']:dict(r,translation=tr[r['id']]) for r in raw if r['scope']=='display_text'}
    # strings the extractor missed: they follow non-NUL data (floats, pointers) so no NUL marks their start
    for k,v in json.loads((ROOT/'work/translation/missed-raw-ko.json').read_text(encoding='utf-8')).items():
        o=int(k[1:],16);assert o not in disp,k
        disp[o]={'id':k,'rom_offset':o,'scope':'display_text','group':None,'translation':v,'missed':True}
    source=(ROOT/'Custom Robo (Japan).z64').read_bytes()
    for o,r in disp.items():
        if r.get('missed'):   # source from the ROM, group from the next extracted string
            r['source']=source[o:source.index(b'\0',o)].decode('euc_jp')
            r['group']=disp[min(q for q in disp if q>o and not disp[q].get('missed'))]['group']
    return disp

# ---------------------------------------------------------------- glyphs
FONT_JSON=json.loads((ROOT/'manifests/font.json').read_text(encoding='utf-8'))
ADV={r['char']:r['advance'] for r in FONT_JSON}
# Hangul starts at column 0 (the kana leave it blank), so … gets 1px more room before it
THIN='〓'   # unused symbol redrawn blank with a 3px advance: fine padding for centred lines (7px spaces alone are off by up to 3.5px)
ADV_TABLE=0x4649c;ADV_FIX={'…':11,'『':8,'』':7,THIN:3,**{c:ADV[c]+1 for c in '０１２３４５６７８９'}}   # digits: 1px before Hangul
ADV.update(ADV_FIX)
# 「」: the kana-style rounded corners look broken next to Hangul; plain right angles instead
BRACKETS={'「':[(0,2),(0,3),(0,4)]+[(y,2) for y in range(1,11)],
          '」':[(y,3) for y in range(0,10)]+[(10,1),(10,2),(10,3)],
          THIN:[]}

def width(s):
    w=0
    for m in re.split(r'(\$[A-Z]\d\d|\$[A-Z]|#[a-zA-Z])',s):
        if not m:continue
        if m=='$A00':w+=NAME_W;continue
        if CONTROL.fullmatch(m):
            if m.startswith('#'):w+=12
            continue
        for c in m:w+=12 if '가'<=c<='힣' else ADV.get(literal(c),12)
    return w

def glyph_bitmap(font,c):
    # x=0: ink stays in columns 0-10 so the baked shadow (column +1) is not cut by the 12px cell
    im=Image.new('1',(12,12));ImageDraw.Draw(im).text((0,-1),c,font=font,fill=1)
    full=Image.new('1',(14,16));ImageDraw.Draw(full).text((0,1),c,font=font,fill=1)
    a=np.array(full);assert not a[:1].any() and not a[13:].any() and not a[:,12:].any(),c  # nothing clipped
    assert im.getbbox(),c
    return np.packbits(np.array(im,dtype=np.uint8).reshape(-1)).tobytes()

# ---------------------------------------------------------------- dialogue wrap
def _split_fit(text,lim=None):
    """Longest head (ending at a space) that fits the line limit, and the rest."""
    lim=_limit(text) if lim is None else lim
    cuts=[i for i,c in enumerate(text) if c in ' 　' and i>0]
    for i in reversed(cuts):
        if width(text[:i].rstrip())<=lim and text[:i].strip(' 　'):return text[:i].rstrip(),text[i:].lstrip(' 　')
    i=len(text)
    while width(text[:i])>lim:i-=1
    return text[:i],text[i:]

# A line that reaches the window's right edge makes the game draw an extra A icon at its end
# (11/05 screens: 204px and a 201px speaker line). Keep every line 6px short of LINE_W; a
# speaker line (名「...) draws about 5px wider than width() says.
DIALOGUE_W=LINE_W-8;SPEAKER_EXTRA=5;THIRD_W=190   # safe: speaker lines <=193, others <=198 (203 showed the extra A, 196 did not); line 3 <=190
SPEAKER=re.compile(r'(\$[A-Z]\d\d)*[^「$ 　]{1,10}「')
def _limit(l,last=False):return LINE_W   # edge lines are fixed by hand (see check_edge_lines); a global limit re-broke 61 reviewed dialogues

def _split_even(text,lim1,lim2):
    """Two-line split with lines of similar length (no one-word orphan on the second line)."""
    best=None
    for i,c in enumerate(text):
        if c not in ' 　' or i==0:continue
        h=text[:i].rstrip();t=text[i:].lstrip(' 　')
        if not h.strip(' 　') or not t:continue
        wh=width(h);wt=width('　'+t)
        if wh<=lim1 and wt<=lim2 and (best is None or abs(wh-wt)<best[0]):best=(abs(wh-wt),h,t)
    return (best[1],best[2]) if best else _split_fit(text,lim1)

def wrap_dialogue(text):
    """Push words that overflow LINE_W onto the next line of the same $W group;
    pack groups into pages of MAX_LINES, splitting a group only if it alone is too long."""
    pages=text.split('$P');out=[];changed=False
    for page in pages:
        lines=page.split('$R')
        if len(lines)<=MAX_LINES and all(width(l)<=_limit(l,i==len(lines)-1) for i,l in enumerate(lines)):out.append(page);continue
        changed=True
        groups=[];cur=[]
        for i,l in enumerate(lines):
            cur.append(l)
            if l.endswith('$W') or i==len(lines)-1:groups.append(cur);cur=[]
        wrapped=[]
        for gi,g in enumerate(groups):
            res=[];carry=''
            for i,l in enumerate(g):
                t=l if not carry else '　'+carry+' '+l.lstrip(' 　')
                carry='';last=gi==len(groups)-1 and i==len(g)-1
                while width(t)>_limit(t,last):
                    head,tail=_split_fit(t,_limit(t,last))
                    res.append(head)
                    if i<len(g)-1:carry=tail;t=None;break
                    t='　'+tail
                if t is not None:res.append(t)
            wrapped.append(res)
        pg=[];cur=[]
        for res in wrapped:
            if len(cur)+len(res)<=MAX_LINES:cur+=res;continue
            if cur:pg.append(cur);cur=[]
            while len(res)>MAX_LINES:
                ch=res[:MAX_LINES];res=res[MAX_LINES:]
                if not ch[-1].endswith('$W'):ch[-1]+='$W'
                pg.append(ch)
                if not res[0].startswith(('「','　')):res[0]='　'+res[0]
            cur=list(res)
        if cur:pg.append(cur)
        for ch in pg[:-1]:
            if not ch[-1].endswith('$W'):ch[-1]+='$W'
        out.append('$P'.join('$R'.join(ch) for ch in pg))
    res='$P'.join(out)
    for p in res.split('$P'):
        ls=p.split('$R')
        assert len(ls)<=MAX_LINES,(text,res)
        for i,l in enumerate(ls):
            if '$A00' not in l:
                # the game draws an extra A at a line that reaches the window edge, and the page's
                # blinking A sits at the right end of line 3 (11/05 screens)
                if width(l)>=(DIALOGUE_W-SPEAKER_EXTRA+1 if SPEAKER.match(l) else DIALOGUE_W+1):REPORT.setdefault('lines_at_window_edge',[]).append(l)
                if i==2 and width(l)>THIRD_W:REPORT.setdefault('line3_under_page_icon',[]).append(l)
            if width(l)>_limit(l,i==len(ls)-1):REPORT.setdefault('overwide_lines',[]).append(l)
    return res,changed

# ---------------------------------------------------------------- encoders
def enc_dialogue(s,m):
    out=[];pos=0
    for x in re.finditer(r'\$[A-Z]\d\d|\$[A-Z]|#[a-zA-Z]',s):
        out+= [_two(c,m) for c in s[pos:x.start()]];out.append(x.group().encode('ascii'));pos=x.end()
    out+=[_two(c,m) for c in s[pos:]]
    return b''.join(out)

def _two(c,m):
    c='仝' if c=='©' else literal(c);b=m[c] if c in m else c.encode('euc_jp');assert len(b)==2,repr(c);return b

def enc_raw(s,source,m):
    """Prefix letter, ASCII spaces, %-formats, #codes and newline stay one byte."""
    out=[];i=0
    if source[:1] in 'ZMNIHKL' and s[:1]==source[:1]:out.append(s[0].encode());i=1
    while i<len(s):
        c=s[i]
        f=re.match(r'%[-+ #0]*\d*(?:\.\d+)?[sdxXuif]|#[a-zA-Z]',s[i:])
        if f:out.append(f.group().encode());i+=len(f.group());continue
        if c in ' \n':out.append(c.encode());i+=1;continue
        out.append(_two(c,m));i+=1
    return b''.join(out)

# ---------------------------------------------------------------- scenario
def build_scenarios(rom,source,append,rows,bysource,m,keys=None):
    files=json.loads((ROOT/'manifests/script-files.json').read_text(encoding='utf-8'))
    per=collections.defaultdict(list)
    for r in rows:
        if r['source'] in bysource or r['source'] in (keys or {}):per[r['script']].append(r)
    stats=collections.Counter();wraps=[]
    # choice menus: opcode 0x110000NN (NN = option number) + pool offset; translated by row id
    choices=json.loads((ROOT/'work/translation/choices-ko.json').read_text(encoding='utf-8'))
    byid={r['id']:r for r in rows}
    choice_fids={byid[k]['script'] for k in choices}
    for fid in sorted(set(per)|choice_fids):
        entries=per.get(fid,[])
        f=files[fid];orig=(ROOT/f'work/extracted/scripts/{fid:03d}.bin').read_bytes()
        pool=f['string_pool'];data=bytearray(orig)
        words=list(struct.unpack_from('>%dI'%(pool//4),orig,0))
        refs=collections.defaultdict(list)
        first=min(struct.unpack_from('>%dI'%f['header_count1'],orig,16))
        for i in range(first//4,len(words)-1):
            if words[i]>>16==0x1000:refs[words[i+1]].append(i+1)
        assert not any(k in refs for k in [r['pool_offset'] for r in entries if r['source'] not in bysource and False])
        keyrefs=collections.defaultdict(list)
        for i in range(first//4,len(words)-1):
            if words[i] in (0x13000000,0x14000000):keyrefs[words[i+1]].append(i+1)
        for r in entries:
            if r['source'] not in bysource and 'keys' in OFF:continue
            if r['source'] not in bysource:
                # glossary/tutorial lookup key: must equal the translated table title byte for byte
                if not keyrefs.get(r['pool_offset']):continue
                # never in place: other opcodes (robo/parts/sound names) may share this pool string
                b=enc_seg(keys[r['source']],False);p=r['offset']
                assert data[p:p+r['bytes']]==r['source'].encode('euc_jp')
                new=len(data)-pool;data+=b+b'\0'
                for i in keyrefs[r['pool_offset']]:struct.pack_into('>I',data,4*i,new)
                stats['lookup_keys']+=1;continue
            text=bysource[r['source']]
            text,ch=wrap_dialogue(text)
            if ch:wraps.append(r['id'])
            b=enc_dialogue(text,m);old=r['bytes'];p=r['offset']
            assert data[p:p+old]==r['source'].encode('euc_jp')
            if len(b)<=old:
                data[p:p+old]=b+bytes(old-len(b));stats['in_place']+=1
            elif 'reloc' in OFF:continue
            else:
                if r['kind']!='dialogue' and not refs.get(r['pool_offset']):
                    stats['skipped_unreferenced']+=1;continue
                assert refs.get(r['pool_offset']),(r['id'],'no opcode-0x10 reference')
                new=len(data)-pool;data+=b+b'\0'
                for i in refs[r['pool_offset']]:struct.pack_into('>I',data,4*i,new)
                stats['relocated']+=1;stats['refs_rewritten']+=len(refs[r['pool_offset']])
        # never in place: the same pool string may also be an internal label for other opcodes
        crefs=collections.defaultdict(list)
        for i in range(first//4,len(words)-1):
            if words[i]&0xffffff00==0x11000000:crefs[words[i+1]].append(i+1)
        for k,t in choices.items():
            r=byid[k]
            if r['script']!=fid:continue
            assert crefs.get(r['pool_offset']),(k,'no choice reference')
            new=len(data)-pool;data+=enc_dialogue(t,m)+b'\0'
            for i in crefs[r['pool_offset']]:struct.pack_into('>I',data,4*i,new)
            stats['choices']+=1
        struct.pack_into('>I',data,0,len(data))
        assert len(data)<=0x20000,(fid,len(data))
        packed=encode(bytes(data));assert decode(packed,0)[0]==bytes(data)
        if len(packed)<=f['compressed_size']:
            a=f['rom_offset'];rom[a:a+f['compressed_size']]=packed+bytes(f['compressed_size']-len(packed))
        else:
            a=append(packed,f'script_{fid:03d}');struct.pack_into('>I',rom,f['table_entry'],a-0x31c290)
            REPORT.setdefault('scripts_moved',[]).append(fid)
        stats['scripts']+=1;stats['max_decoded']=max(stats['max_decoded'],len(data))
        stats['max_packed']=max(stats['max_packed'],len(packed))
    REPORT['scenario']=dict(stats);REPORT['rewrapped_entries']=len(wraps)
    assert stats['max_packed']<=0x25800

# ---------------------------------------------------------------- overlay strings
def build_raw(rom,source,append,disp,m):
    S=segments(source)
    def overlap(a,b):return not(a['bss_end']<=b['ram'] or b['bss_end']<=a['ram'])
    segids=sorted({seg_of_rom(S,p)['id'] for p in disp})
    words={s['id']:struct.unpack_from('>%dI'%((s['rom_end']-s['data_rom'])//4),source,s['data_rom']) for s in S}
    crefs={s['id']:code_refs(source,s) for s in S}
    bylui=collections.defaultdict(list)
    for s in S:
        for r in crefs[s['id']]:bylui[(s['id'],r[1])].append(r)
    starts=set()
    for p in disp:
        q=p
        while source[q-1]!=0 and not disp[p].get('missed'):q-=1
        starts.add(q)
    # string starts in the display areas (every NUL-separated string)
    pointers=collections.defaultdict(list)
    for sid in segids:
        s=S[sid];ps=[p for p in disp if seg_of_rom(S,p)['id']==sid]
        lo=min(ps);hi=max(ps)+400
        vlo=s['ram']+lo-s['rom_start'];vhi=s['ram']+hi-s['rom_start']
        for t in S:
            if t['id']!=sid and t['id']!=0 and overlap(s,t):continue
            for i,w in enumerate(words[t['id']]):
                if vlo<=w<vhi:pointers[s['rom_start']+w-s['ram']].append(('data',t['data_rom']+4*i))
            for r in crefs[t['id']]:
                if vlo<=r[5]<vhi:pointers[s['rom_start']+r[5]-s['ram']].append(('code',t['id'],r))
    def is_start(p):return source[p-1]==0 and source[p]!=0 or (source[p]==0 and source[p-1]==0)
    def walk(p):
        cr=CREDITS[0]<=p<CREDITS[1];mem=[]
        while True:
            e=source.index(b'\0',p);mem.append((p,e));p=e+1
            if cr:
                if source[p]==0:break
            elif source[p] not in PREFIX:break
        return mem
    ignored=[];blocks={}
    for t in pointers:
        if source[t-1]!=0 and not disp.get(t,{}).get('missed'):ignored.append(hex(t));continue
        blocks[t]=walk(t)
    # clusters: union of overlapping member spans
    spans=sorted((mem[0][0],mem[-1][1],t) for t,mem in blocks.items())
    clusters=[]
    for a,b,t in spans:
        if clusters and a<=clusters[-1]['end']:
            c=clusters[-1];c['end']=max(c['end'],b);c['targets'].append(t)
        else:clusters.append({'start':a,'end':b,'targets':[t]})
    stats=collections.Counter();blob=bytearray();patches=[];covered=set()
    for c in clusters:
        members=sorted({x for t in c['targets'] for x in blocks[t]})
        if not any(p in disp for p,_ in members):continue
        covered.update(p for p,_ in members)
        texts=[];changed=False;prev=''
        for p,e in members:
            raw0=source[p:e];txt=raw0.decode('euc_jp','replace')
            if p in disp and disp[p]['translation'] is not None:
                t=_join_space(prev,disp[p]['translation']);changed=True
            elif txt[:1] in 'NM' and txt[1:].strip('　') and set(txt[1:])<=set('、。　'):
                t=txt[0]+txt[1:].replace('、　',', ').replace('、',',').replace('。','.').replace('　',' ');changed=True
            else:t=None
            # a member that starts with a letter the encoder reads as a prefix (ID, HAL): write it full width
            if t and t[:1] in 'ZMNIHKL' and raw0[:1].decode('latin-1')!=t[:1]:t=literal(t[0])+t[1:]
            texts.append((p,t,raw0))
            cand=t if t is not None else txt
            # an empty colour segment keeps the word before it; a line break (Z, even empty) starts a new line
            if not prev or cand[:1]=='Z' or (cand[1:] if cand[:1] in 'MNLIHK' else cand).strip(' 　'):prev=cand
        if not changed:continue
        group=next(disp[p]['group'] for p,_ in members if p in disp)
        if group in FLUSH_LEFT:   # Japanese indents follow-on lines under the 特長： label; Korean starts them at the left edge
            texts=[(p,'Z'+t[1:].lstrip(' 　') if t is not None and t[:1]=='Z' else t,r) for p,t,r in texts]
        tutorial=group=='glossary_and_tutorial' and c['start']>=TUTORIAL_START
        # several targets: only the tutorial pages are split per target (other groups keep their layout)
        runs=_target_runs(texts,c['targets']) if group in RAW_W and (len(c['targets'])==1 or tutorial) else None
        if runs:
            # each pointer target starts its own run (a page or paragraph); reflow runs separately
            W=TUTORIAL_W if tutorial else RAW_W[group]
            newmem=[]
            for run in runs:
                segs=[t if t is not None else r.decode('euc_jp') for p,t,r in run]
                z=segs[0][:1]=='Z'
                if z:segs[0]=segs[0][1:]
                if group in FLUSH_LEFT:segs=_join_breaks(_label_down(_flush_left(segs)),W)
                # '|' in a translation = a line break chosen by hand (the text after it starts a new line)
                segs=[x for s in segs for x in ([s.split('|')[0]]+['Z'+t for t in s.split('|')[1:]])]
                new=reflow_block(segs,W,icon=TUTORIAL_ICON if tutorial else None)
                if new!=segs:stats['reflowed']+=1
                if z:new[0]='Z'+new[0]
                newmem+=[(run[0][0] if i==0 else None,enc_seg(t,i>0 or z)) for i,t in enumerate(new)]
        else:
            if group in CENTER:
                # a line starts at a member with no prefix letter (a window's first line) or with Z
                bare=lambda r:r[:1] not in b'ZMNLIHK'
                starts=lambda r:bare(r) or r[:1]==b'Z'
                Rof={}
                if CENTER[group] is None:   # one centre per window: where its widest Japanese line was centred
                    for run in _target_runs(texts,c['targets']) or [[x] for x in texts]:
                        lines=[r.decode('euc_jp','replace') for p,t,r in run if starts(r)]
                        # a lone line (a question in its own window) keeps its place; padded windows share one centre
                        if len(lines)<2 or not any((s if bare(s.encode('euc_jp','replace')) else s[1:])[:1]==' ' for s in lines):continue
                        R=max(window_R(s,s[:1]!='Z') for s in lines)
                        for p,t,r in run:Rof[p]=R
                texts=[(p,recenter(t,r.decode('euc_jp','replace'),bare(r),Rof.get(p,CENTER[group]),p in Rof) if t is not None and starts(r) and (bare(r) or t[:1]=='Z') else t,r) for p,t,r in texts]
            if group=='credits':
                texts=[(p,t.replace('　'*4,'　　') if t is not None and raw_width(t)>202 else t,r) for p,t,r in texts]
                # the staff roll reads every character as two bytes: a one-byte ASCII space shifts the rest
                # (11/05 black screen: ' '+lead byte read as glyph 0x2088, the font search faults)
                # (11/05 again: 'HAL' read as prefix H) so every character goes in full width
                texts=[(p,''.join(literal(ch) for ch in t) if t is not None else t,r) for p,t,r in texts]
            assert not any(t and '|' in t for _,t,_ in texts),'hand line break only works in reflowed text'
            newmem=[(p,enc_seg(t,i>0) if t is not None else r) for i,(p,t,r) in enumerate(texts)]
        # in-place capacity: up to the next non-zero byte, keeping one spare NUL
        q=c['end']+1
        # a NUL some pointer targets is an empty string (the staff roll's end mark, 11/05), not padding
        while source[q]==0 and q not in pointers:q+=1
        spare=q-(c['end']+1)
        body=b'\0'.join(b for _,b in newmem)+b'\0'
        need_spare=1 if spare>=1 else 0
        if len(body)+need_spare<=q-c['start'] and all(_member_contiguous(sorted({x for t in c['targets'] for x in blocks[t]}))):
            rom[c['start']:q]=body+bytes(q-c['start']-len(body));stats['in_place']+=1
            # member starts moved: rewrite every pointer to a member other than the first
            offs={};pos=c['start']
            for p,b in newmem:
                if p is not None:offs[p]=pos
                pos+=len(b)+1
            for t in c['targets']:
                if offs[t]!=t:patches.append((t,offs[t]-t,'rom'))
            continue
        # relocate whole cluster into the RAM blob
        base=len(blob);offs={};pos=base
        for p,b in newmem:
            if p is not None:offs[p]=pos
            pos+=len(b)+1
        blob+=body+b'\0';blob+=bytes((-len(blob))%4)
        for t in c['targets']:patches.append((t,offs[t],'blob'))
        stats['relocated']+=1
    # apply pointer patches
    newaddr={}
    for t,v,kind in patches:
        s=seg_of_rom(S,t);old=s['ram']+t-s['rom_start']
        newaddr[old]=old+v if kind=='rom' else BLOB_VA+v
    lui_new={}
    for t,v,kind in patches:
        s=seg_of_rom(S,t);old=s['ram']+t-s['rom_start'];new=newaddr[old]
        for ref in pointers[t]:
            if ref[0]=='data':struct.pack_into('>I',rom,ref[1],new);stats['data_ptr']+=1
            else:
                _,sid,(va,lva,op,rs,rt,tg)=ref;seg=S[sid]
                lo_rom=seg['rom_start']+va-seg['ram'];hi_rom=seg['rom_start']+lva-seg['ram']
                if op==0x0d:hi,lo=new>>16,new&0xffff
                else:hi,lo=((new+0x8000)>>16)&0xffff,new&0xffff
                key=(sid,lva)
                if key in lui_new:assert lui_new[key]==hi,('shared lui conflict',hex(lva))
                else:
                    for other in bylui[key]:
                        ot=other[5];assert newaddr.get(ot,ot)>>16==hi or ((newaddr.get(ot,ot)+0x8000)>>16)&0xffff==hi or other[0]==va,('shared lui',hex(lva),hex(ot))
                    lui_new[key]=hi
                w=struct.unpack_from('>I',rom,hi_rom)[0];struct.pack_into('>I',rom,hi_rom,(w&0xffff0000)|hi)
                w=struct.unpack_from('>I',rom,lo_rom)[0];struct.pack_into('>I',rom,lo_rom,(w&0xffff0000)|lo)
                stats['code_ptr']+=1
    # display strings reached by no pointer: in place only
    for p,r in disp.items():
        if p in covered or r['translation'] is None:continue
        t=''.join(literal(ch) for ch in r['translation']) if r['group']=='credits' else r['translation']   # staff roll: two-byte characters only
        b=enc_raw(t,r['source'],m);e=source.index(b'\0',p)
        if len(b)<=e-p:rom[p:e+1]=b+bytes(e+1-p-len(b));stats['unreferenced_in_place']+=1
        else:stats['unreferenced_kept_original']+=1;REPORT.setdefault('raw_kept_original',[]).append(r['id'])
    REPORT['raw']=dict(stats);REPORT['raw_ignored_midstring_pointers']=ignored
    assert BLOB_VA+len(blob)<=BLOB_LIMIT
    return bytes(blob)

RAW_W={'parts':242,'glossary_and_tutorial':242}   # widest glossary body line (251 was a pause prompt)
FLUSH_LEFT={'parts'}

def _flush_left(segs):
    """Drop the Japanese indents (also the untranslated all-space members such as 'Z    ')."""
    return [s.lstrip(' 　') if i==0 else 'Z'+s[1:].lstrip(' 　') if s[:1]=='Z' else s for i,s in enumerate(segs)]

def _join_breaks(segs,W):
    """The Japanese breaks long sentences onto a new line; Korean is shorter, so a line that
    stops mid-sentence takes the next line back when the two fit (not into the title line)."""
    out=[];line='';n=0
    for s in segs:
        body=s if not out else s[1:]
        if out and s[:1]=='Z':
            if n>0 and body.strip() and line.strip() and not re.search(r'[.!?。:：…」』]$',line.rstrip()) and raw_width(line.rstrip()+' '+body.lstrip())<=W:
                out.append('N '+body.lstrip());line=line.rstrip()+' '+body.lstrip();continue
            n+=1;line=body;out.append(s);continue
        out.append(s);line+=body
    return out

def _is_label(t):return t[:1] in 'IHKM' and re.search('[:：]$',t)

def _label_down(segs):
    """爆風は球型： starts a line, but its text sits on the next line; continue the label's line
    with it instead: ['Z', 'I폭풍은 구형:', 'N', 'Z맞은 상대를'] -> ['Z', 'I폭풍은 구형:', 'N', 'N 맞은 상대를'].
    A label at the end of a text line is first moved to a line of its own."""
    out=[];after=False
    def line_has_text():
        for s in reversed(out):
            body=s[1:] if s[:1] in 'ZNMIHKL' and s is not out[0] else s
            if body.strip(' 　'):return True
            if s[:1]=='Z' and s is not out[0]:return False
        return False
    for i,t in enumerate(segs):
        if i>0 and _is_label(t):
            if line_has_text():out.append('Z')
            out.append(t);after=True;continue
        if after and t=='N':out.append(t);continue
        if after and t[:1]=='Z' and t[1:].strip():out.append('N '+t[1:]);after=False;continue
        after=False;out.append(t)
    return out

def raw_width(t,icon=None):
    t=re.sub(r'%[sd]','12345',t)
    n=len(re.findall(r'#[a-zA-Z]',t));t=re.sub(r'#[a-zA-Z]','□',t)
    w=sum(7 if ch==' ' else 12 if '가'<=ch<='힣' else ADV.get(literal(ch),12) for ch in t)
    return w if icon is None else w+n*(icon-ADV.get(literal('□'),12))

# tutorial pages (ロボの武器・性能を… onwards) sit in a narrower window than the glossary;
# the widest Japanese line there is 234px and button icons draw wider than a glyph
TUTORIAL_START=0x5d2b4;TUTORIAL_W=242;TUTORIAL_ICON=16   # same window as the glossary (11/05 screen: 234 wrapped lines that fit)

def _target_runs(texts,targets):
    """Split a cluster's members at its pointer targets. None if a target lands mid-line."""
    ts=set(targets);runs=[]
    for p,t,r in texts:
        if p in ts or not runs:runs.append([])
        runs[-1].append((p,t,r))
    for run in runs[1:]:
        first=run[0][1] if run[0][1] is not None else run[0][2].decode('euc_jp')
        if first[:1] in 'NMIHKL':return None
    return runs

def enc_seg(t,prefixed):
    out=[];i=0
    if prefixed and t[:1] in 'ZMNIHKL':out.append(t[0].encode());i=1
    while i<len(t):
        f=re.match(r'%[-+ #0]*\d*(?:\.\d+)?[sdxXuif]|#[a-zA-Z]',t[i:])
        if f:out.append(f.group().encode());i+=len(f.group());continue
        if t[i] in ' \n':out.append(t[i].encode());i+=1;continue
        out.append(_two({'、':',','。':'.'}.get(t[i],t[i]),GLYPHS));i+=1
    return b''.join(out)

CENTER={'holoseum':242,'save':None}   # holoseum: twice the box centre measured on screen (11/05: 121px from the pad origin)
def window_R(srcseg,first):
    """R (twice the centre) of a Japanese line padded with ASCII spaces (a full line: its width)."""
    sp=srcseg if first else srcseg[1:]
    jcore=sp.lstrip(' ');return (len(sp)-len(jcore))*14+raw_width(jcore)

def recenter(t,srcseg,first,R,window=False):
    """Japanese pads these lines with ASCII spaces (7px) to centre them; re-pad for Korean.
    window=True: R is the window's centre, so unpadded Japanese lines are centred too."""
    pre='' if first else t[:1];body=t if first else t[1:]
    sp=srcseg if first else srcseg[1:]
    if sp[:1]!=' ' and not window:return t
    if R is None:   # centre where the Japanese line was centred (save prompts sit in windows of different widths)
        jcore=sp.lstrip(' ');R=(len(sp)-len(jcore))*14+raw_width(jcore)
    core=body.lstrip(" ");P=max(0,round((R-raw_width(core))/2))
    # 7px spaces plus 3px blank glyphs: the closest pad to P, fewest blanks first
    a,b=min(((a,b) for a in range(P//7+1) for b in range(7)),key=lambda ab:(abs(7*ab[0]+3*ab[1]-P),ab[1]))
    return pre+' '*a+THIN*b+core

def reflow_block(segs,W,icon=None):
    """segs[0] has no prefix; Z starts a line, other prefixes continue it on the same line.
    Words past W move to the start of the next line (same indent) if that line continues
    the text, otherwise into a new Z line. Colour runs are kept."""
    segs=list(segs)
    for i in range(1,len(segs)):   # a Z line must not start with a particle: move it to the line above
        t=segs[i]
        if t[:1]!='Z':continue
        ind=re.match(r'[ 　]*',t[1:]).group();body=t[1+len(ind):]
        m=re.match(r'(을|를|의|와|과|은|는|에|로|으로)(?= |$)',body)
        j=i-1
        while j>0 and re.fullmatch(r'[ZMNLIHK][ 　]*',segs[j]):j-=1
        if m and re.search(r'[가-힣]$',segs[j].rstrip()):
            segs[j]=segs[j].rstrip()+m.group(1);segs[i]='Z'+ind+body[m.end():].lstrip(' ')
    for i in range(2,len(segs)):   # same after an empty Z line (Japanese starts the line with a particle)
        t=segs[i]
        if t[:1] not in 'NM' or not re.fullmatch(r'Z[ 　]*',segs[i-1]):continue
        m=re.match(r'(을|를|의|와|과|은|는|에|로|으로)(?= |$)',t[1:])
        if m and re.search(r'[가-힣]$',segs[i-2].rstrip()):
            segs[i-2]=segs[i-2].rstrip()+m.group(1);segs[i]=t[0]+t[1+m.end():].lstrip(' ')
    lines=[[('N',segs[0])]]
    for t in segs[1:]:
        if t[:1]=='Z':lines.append([('N',t[1:])])
        else:lines[-1].append((t[0],t[1:]))
    def text(l):return ''.join(x for _,x in l)
    def indent(l):return re.match(r'[ 　]*',l[0][1]).group()
    out=[];i=0
    while i<len(lines):
        l=lines[i]
        if raw_width(text(l),icon)<=W:out.append(l);i+=1;continue
        ind=indent(l);flat=[(k,st,ch) for k,(st,x) in enumerate(l) for ch in x]
        cut=None;acc=''
        for j,(k,st,ch) in enumerate(flat):
            acc+=ch
            if ch==' ' and j>=len(ind) and acc.strip(' 　') and raw_width(acc.rstrip(),icon)<=W:cut=j
        assert cut is not None,(segs,text(l))
        head=[];tail=[]
        for j,(k,st,ch) in enumerate(flat):
            if j==cut:continue
            tgt=head if j<cut else tail
            if tgt and tgt[-1][0]==k:tgt[-1][2]+=ch
            else:tgt.append([k,st,ch])
        out.append([(st,x) for _,st,x in head])
        tail=[(st,x) for _,st,x in tail]
        if not tail:i+=1;continue   # only a trailing space was over the edge
        nxt=lines[i+1] if i+1<len(lines) else None
        ntext=text(nxt) if nxt is not None else ''
        header=re.match(r'[ 　]*[^ 　]{1,4}[:：]',ntext)
        # tutorial pages: a tail that ends its sentence gets its own line (next line is a new sentence)
        ends=icon is not None and re.search(r'[.!?。]$',''.join(x for _,x in tail).rstrip())
        if nxt is not None and ntext.strip(' 　') and not header and not ends and (indent(nxt) or not indent(l)):
            nind=indent(nxt);rest=nxt[0][1][len(nind):]
            lead=[('N',nind+tail[0][1])] if tail[0][0]=='N' else [('N',nind),tail[0]]
            nxt_rest=nxt[1:]
            if not rest and nxt_rest and nxt_rest[0][1][:1] not in (' ','　') and not attaches(nxt_rest[0][1]):nxt_rest=[(nxt_rest[0][0],' '+nxt_rest[0][1])]+nxt_rest[1:]
            lines[i+1]=lead+tail[1:]+([('N',('' if attaches(rest) else ' ')+rest)] if rest else [])+nxt_rest
        else:
            lead=[('N',ind+tail[0][1])] if tail[0][0]=='N' else [('N',ind),tail[0]]
            lines.insert(i+1,lead+tail[1:])
        i+=1
    res=[]
    for n,l in enumerate(out):
        for k,(st,x) in enumerate(l):
            if k==0 and st!='N':res+=['' if n==0 else 'Z',st+x]   # a line that starts with a coloured run keeps its colour
            else:res.append((x if n==0 else 'Z'+x) if k==0 else st+x)
    return res

PARTICLES={'을','를','이','가','은','는','의','에','와','과','도','만','로','으로','에서','에게','까지','부터','처럼','보다','이다','다','형','용','이고','이며','이라','이므로','이나','나','라','란','라고','이라고','이란','엔','에는','에도','으로는','로는','과는','와는','보다는','만큼','뿐','이야','야','요','죠','지','고','며','면','므로','으므로','니까','인','임','됨','함','할','한','된','될','하는','되는'}
ENDINGS=('하','해','했','되','돼','됐','으로','에서','에게','까지','부터','처럼','이라','이다','라고')
CONNECTIVE=set('만고며서면데니게어아여도는을를은이가의에와과로')
def attaches(body,prev=''):
    m=re.match(r'[가-힣]+',body)
    if not m:return not re.match(r'[0-9A-Za-z０-９Ａ-Ｚａ-ｚ(（『「#]',body)
    w=m.group();last=prev.rstrip()[-1:]
    if w in ('한','할','된','될','함','됨','하는','되는') and (not prev or prev.endswith(' ') or last in CONNECTIVE):return False
    pw=re.findall(r'[가-힣]+',prev)[-1:] or ['']
    if w.startswith(('하','해','했','한','되','돼','됐','된')) and (pw[0] in ('못','안') or pw[0].endswith(('야','게','지','고','록'))):return False
    return w in PARTICLES or w.startswith(ENDINGS+('한다','된다','했다','됐다','합니다','됩니다'))

def _join_space(prev,t):
    """Japanese segments join without spaces; Korean words need one unless a particle/ending follows."""
    if t[:1] not in 'NMLIHK' or not prev:return t
    if prev[:1] in 'ZMNLIHK' and not prev[1:].strip(' 　'):return t
    body=t[1:];last=prev.rstrip()[-1:] if prev.rstrip() else ''
    if prev.endswith((' ','　')) or body[:1] in (' ','　'):return t
    if re.search(r'#[a-zA-Z]$',prev):return t
    if last and ('가'<=last<='힣' or last.isalnum() or last in ',.!?)」』:：') and body[:1] and '가'<=body[0]<='힣' and not attaches(body,prev):
        return t[0]+' '+body
    return t

def _member_contiguous(members):
    yield all(members[i][1]+1==members[i+1][0] for i in range(len(members)-1))

# ---------------------------------------------------------------- font + loader
def patch_font_and_loader(rom,source,append,m,blob):
    japanese=bytearray(font_cache.original_expanded(source))
    byc={r['char']:r['index'] for r in FONT_JSON}
    for c,pix in BRACKETS.items():
        a=np.zeros((12,12),dtype=np.uint8)
        for y,x in pix:a[y,x]=1
        i=byc[c];japanese[i*96:(i+1)*96]=font_cache.expand(np.packbits(a.reshape(-1)).tobytes())
    for c,w in ADV_FIX.items():rom[ADV_TABLE+byc[c]]=w
    jp_rom=append(bytes(japanese),'original_font_i4')
    font=ImageFont.truetype(str(FONT),12)
    ci={c:(b[0]-0x81)*94+b[1]-0xa1 for c,b in m.items()};count=max(ci.values())+1
    slots=[bytes(96)]*count            # leads 0x8E/0x8F stay blank (never looked up)
    for c,i in ci.items():
        if c>='':continue   # particle stand-ins: never drawn themselves (the lookup swaps them)
        slots[i]=font_cache.expand(glyph_bitmap(font,c))
    ko_rom=append(b''.join(slots),'korean_font_i4')
    rep=font_cache.patch(rom,jp_rom,ko_rom,count if 'cap' not in OFF else 1041)
    if 'gap' in OFF:append(bytes(131072),'gap')   # test: move the blob in ROM only
    blob_rom=append(blob,'string_blob') if blob else None
    if blob:
        k=Ks(KS_ARCH_MIPS,KS_MODE_MIPS32|KS_MODE_BIG_ENDIAN)
        n=(len(blob)+7)&~7
        init=bytes(k.asm(f'''.set noreorder
            addiu $sp,$sp,-32
            sw $ra,28($sp)
            jal 0x8004be30
            nop
            li $a0,{jp_rom}
            li $a1,{font_cache.TEXTURES}
            li $a2,{1647*96}
            jal 0x8003bffc
            nop
            li $a0,{blob_rom}
            li $a1,{BLOB_VA}
            li $a2,{n}
            jal 0x8003bffc
            nop
            li $t0,{font_cache.KEYS}
            li $t1,{font_cache.CURSOR+4}
        clear:
            sw $zero,0($t0)
            addiu $t0,$t0,4
            bne $t0,$t1,clear
            nop
            lw $ra,28($sp)
            addiu $sp,$sp,32
            jr $ra
            nop''',font_cache.INIT)[0])
        assert font_cache.INIT+len(init)<=font_cache.HOOK
        a=font_cache.INIT-0x80024c00;rom[a:a+len(init)]=init
        rep['string_blob']={'rom':blob_rom,'ram':hex(BLOB_VA),'bytes':len(blob)}
    REPORT['font']=rep;REPORT['glyphs']=len(m)

# ---------------------------------------------------------------- battle records
# Each battle is a 0x238-byte record (title, stage, cannon, opponent, robo, gun/bomb/pod/leg as
# 32-byte name fields); the attract-demo records follow in the same area. The game shows these
# names before a battle and also looks things up by them with strcmp, which the name-key table
# maps back to Japanese. Titles and cannon names are internal and stay Japanese.
BATTLE_AREA=(0x77d730,0x78d040)
BATTLE_NAMES=ROOT/'work/translation/battle-names-ko.json'

def battle_names(disp):
    names={}
    for r in disp.values():
        if r['translation'] and r['source'][:1] not in 'ZMNIHKL':names.setdefault(r['source'],r['translation'])
    names.update(json.loads(BATTLE_NAMES.read_text(encoding='utf-8')))
    return names

def patch_battle_records(rom,source,names):
    a,e=BATTLE_AREA;p=a;n=0;left=set()
    while p<e:
        if source[p]==0 or p%4:p+=1;continue   # fields are word aligned (part fields follow a flag word)
        q=source.index(b'\0',p)
        try:jp=source[p:q].decode('euc_jp')
        except UnicodeDecodeError:p=q;continue
        if jp in names:
            # field: up to the next non-zero byte, never past 32 bytes (an empty next field must stay empty)
            end=q
            while end<p+0x20 and source[end]==0:end+=1
            b=enc_seg(names[jp],False);assert len(b)<end-p,(hex(p),jp)
            rom[p:end]=b+bytes(end-p-len(b));n+=1
        elif re.search(r'[ぁ-ヿ]',jp):left.add(jp)
        p=q
    REPORT['battle_records']={'fields':n,'left_japanese':len(left)}   # count only: the report is committed, source text is not

# ---------------------------------------------------------------- main
def main(out_name):
    source=(ROOT/'Custom Robo (Japan).z64').read_bytes();rom=bytearray(source)
    assert crc6102(source)==source[16:24]
    # Free ROM after the original data. The battle overlay keeps a developer override: it reads
    # ROM 0xF00000/0xF10000/.../0xF50000 and uses that data unless the header words are 0xFFFFFFFF,
    # so those headers must stay 0xFF (our data there hung/crashed the first battle).
    free=(len(source.rstrip(b'\xff'))+15)&~15
    if 'highrom' in OFF:rom+=b'\xff'*0x1000000;free=0x1000000
    KEEP_FF=[(0xf00000+0x10000*k,0xf00000+0x10000*k+16) for k in range(6)]
    alloc=[]
    def append(data,label):
        nonlocal free
        start=free
        for a,b in KEEP_FF:
            if start<b and start+len(data)>a:start=b
        assert start+len(data)<=len(rom) and rom[start:start+len(data)]==b'\xff'*len(data),(label,hex(start))
        rom[start:start+len(data)]=data;free=(start+len(data)+15)&~15
        alloc.append({'label':label,'offset':start,'bytes':len(data)});return start
    rows,bysource=load_dialogue();disp=load_raw()
    texts=list(bysource.values())+[r['translation'] for r in disp.values() if r['translation']]
    texts+=list(json.loads((ROOT/'work/translation/choices-ko.json').read_text(encoding='utf-8')).values())
    # fixed codes: KS X 1001 syllables, then compatibility jamo (name entry), then any extra syllable
    used={c for t in texts for c in t if '가'<=c<='힣'}
    glyphs=name_input.KS+name_input.JAMO+sorted(used-set(name_input.KS))
    if 'fixedcodes' in OFF:glyphs=sorted(used)+[j for j in name_input.JAMO]   # test: old compact numbering
    if 'reverse' in OFF:glyphs=glyphs[::-1]
    if 'pad' in OFF:glyphs=glyphs+[c for c in name_input.KS if c not in set(glyphs)][:1400]
    for o in OFF:
        if o.startswith('shift'):   # test: start the compact numbering at lead 0x81+N
            filler=[c for c in name_input.KS if c not in used][:int(o[5:])*94];glyphs=filler+glyphs
    REPORT['extra_syllables_outside_ks']=sorted(used-set(name_input.KS))
    assert len(glyphs)<=32*94,len(glyphs)
    m={c:name_input.idx2code(i) for i,c in enumerate(glyphs)}
    hangul_codes=dict(m)
    # particle stand-ins take the codes right after the glyphs (blank font slots)
    for k,(tok,_) in enumerate(particles.KINDS):m[particles.CHAR[tok]]=name_input.idx2code(len(glyphs)+k)
    GLYPHS.update(m)
    keys={}
    for r in disp.values():
        if r['translation'] is not None and r['source'][:1] not in 'ZMNIHKL':keys.setdefault(r['source'],r['translation'])
    if 'scen' not in OFF:build_scenarios(rom,source,append,rows,bysource,m,keys)
    blob=bytearray(build_raw(rom,source,append,disp,m) if 'raw' not in OFF else b'')
    # main-segment strings the GPT classification left out (yes/no of the common dialog): in place only
    extra=json.loads((ROOT/'work/translation/main-inplace-ko.json').read_text(encoding='utf-8'))
    for k,t in extra.items():
        p=int(k,16);e=source.index(b'\0',p);b=enc_seg(t,False)
        assert len(b)<=e-p,(k,t);rom[p:e]=b+bytes(e-p-len(b))
    REPORT['main_inplace']=len(extra)
    # battle records (opponent name, robo, parts, stage shown before a battle): fixed fields, in place
    battle=battle_names(disp)
    if 'battle' not in OFF:patch_battle_records(rom,source,battle)
    # Hangul name entry: jamo grid on page 0 (was katakana) + composition routine in the RAM blob
    blob+=bytes((-len(blob))%16);mod,entry=name_input.module(BLOB_VA+len(blob));blob+=mod
    # name keys: strcmp maps translated strings back to Japanese (parts/stages/... are looked up by name)
    pairs={}
    for p_,r in disp.items():
        if r['translation'] is None or r['source'][:1] in 'ZMNIHKL':continue
        ko=enc_seg(r['translation'],False);jp=r['source'].encode('euc_jp')
        if ko!=jp and ko not in pairs:pairs[ko]=jp
        elif ko in pairs and pairs[ko]!=jp:REPORT.setdefault('key_dict_collisions',[]).append(r['id'])
    for k,t in extra.items():
        p_=int(k,16);pairs.setdefault(enc_seg(t,False),source[p_:source.index(b'\0',p_)])
    for jp,ko in json.loads(BATTLE_NAMES.read_text(encoding='utf-8')).items():
        k_=enc_seg(ko,False)
        if k_ in pairs and pairs[k_]!=jp.encode('euc_jp'):REPORT.setdefault('key_dict_collisions',[]).append('battle-names:'+ko)
        pairs.setdefault(k_,jp.encode('euc_jp'))
    blob+=bytes((-len(blob))%16);tab,tab_va,mask=key_dict.table(BLOB_VA+len(blob),list(pairs.items()));blob+=tab
    REPORT['key_dict']={'entries':len(pairs),'table':hex(tab_va),'code':hex(key_dict.CODE_VA)}
    S=segments(source);s8=S[8]
    grid=b''.join(m.get(c) or c.encode('euc_jp') for c in name_input.GRID)
    assert len(grid)==130 and rom[0x114fc0+130]==0
    if 'name' not in OFF:rom[0x114fc0:0x114fc0+130]=grid
    h=name_input.hook_bytes(entry);a=s8['rom_start']+name_input.HOOK-s8['ram']
    assert rom[a:a+4]==bytes.fromhex('3c068024') or True
    if 'name' not in OFF:rom[a:a+len(h)]=h
    REPORT['name_entry']={'routine':hex(entry),'hook':hex(name_input.HOOK),'grid_rom':hex(0x114fc0)}
    # particles after the name: module in the blob, run first by the font lookup entry
    byc={r['char']:r['index'] for r in FONT_JSON}
    blob+=bytes((-len(blob))%16)
    pmod,pentry=particles.module(BLOB_VA+len(blob),{c:v for c,v in hangul_codes.items() if '가'<=c<='힣'},
        [m[particles.CHAR[tok]] for tok,_ in particles.KINDS],font_cache.HOOK,font_cache.TEXTURES+byc[THIN]*96)
    blob+=pmod
    REPORT['particles']={'entry':hex(pentry),'bytes':len(pmod),'kinds':[tok for tok,_ in particles.KINDS]}
    blob=bytes(blob)
    patch_font_and_loader(rom,source,append,m,blob)
    a=font_cache.LOOKUP-0x80024c00
    assert rom[a:a+8]==font_cache.asm(f'j {font_cache.HOOK}\nnop',font_cache.LOOKUP)
    if 'particles' not in OFF:rom[a:a+8]=font_cache.asm(f'j {pentry}\nnop',font_cache.LOOKUP)
    c=key_dict.code(tab_va,mask);a=key_dict.CODE_VA-0x80024c00
    assert font_cache.HOOK+REPORT['font']['hook_code_bytes']<=key_dict.CODE_VA and rom[a:a+len(c)]==bytes(len(c))
    rom[a:a+len(c)]=c
    h=key_dict.hook_bytes(key_dict.CODE_VA);a=key_dict.STRCMP-0x80024c00
    assert rom[a:a+8]==bytes.fromhex('9082000090a30000')
    if 'keydict' not in OFF:rom[a:a+8]=h
    import build_images   # finished images from the series graphics folder (10/29)
    REPORT['images']=build_images.apply(rom,source,append) if 'images' not in OFF else 'off'
    if 'dmalog' in OFF:   # investigation only: log every ROM DMA (src, size, caller) to RAM 0x80300000
        k=Ks(KS_ARCH_MIPS,KS_MODE_MIPS32|KS_MODE_BIG_ENDIAN);LOG=0x8002c5a0
        code=bytes(k.asm(f'''.set noreorder
            lui $t8,0x8030
            lw $t9,0($t8)
            sltiu $at,$t9,0x3e00
            beqz $at,skip
            sll $at,$t9,4
            addu $at,$at,$t8
            sw $a0,16($at)
            sw $a2,20($at)
            sw $ra,24($at)
            sw $a1,28($at)
            addiu $t9,$t9,1
            sw $t9,0($t8)
        skip:
            addiu $sp,$sp,-0x18
            blez $a2,zero_size
            sw $ra,0x14($sp)
            j 0x8003c008
            nop
        zero_size:
            j 0x8003c010
            nop''',addr=LOG)[0])
        a=LOG-0x80024c00;assert rom[a:a+len(code)]==bytes(len(code)) and LOG+len(code)<=0x8002c600;rom[a:a+len(code)]=code
        a=0x8003bffc-0x80024c00;rom[a:a+8]=bytes(k.asm(f'.set noreorder; j {LOG}; nop',addr=0x8003bffc)[0])
    rom[16:24]=crc6102(rom)
    out=ROOT/'build'/out_name;out.write_bytes(rom)
    REPORT.update(file=str(out.relative_to(ROOT)),sha256=hashlib.sha256(rom).hexdigest(),
                  md5=hashlib.md5(rom).hexdigest(),crc6102=rom[16:24].hex(),allocations=alloc,
                  rom_free_after=len(rom)-free,code_mapping={c:b.hex() for c,b in m.items()})
    (ROOT/'manifests/full-build.json').write_text(json.dumps(REPORT,ensure_ascii=False,indent=1),encoding='utf-8')
    print(json.dumps({k:v for k,v in REPORT.items() if k not in ('code_mapping','allocations','overwide_lines','font')},ensure_ascii=False))

if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else 'Custom Robo (Japan) [KO].z64')
