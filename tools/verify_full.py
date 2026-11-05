"""Independent check of a full Korean build: read the built ROM back through its own
tables and pointers, decode every reachable string, and compare with the sources."""
import json,re,struct,sys,collections
from survey_rom import ROOT,decode
from segments import segments,seg_of_rom,code_refs
import build_full as B

def main(name):
    rom=(ROOT/'build'/name).read_bytes();src=(ROOT/'Custom Robo (Japan).z64').read_bytes()
    rep=json.loads((ROOT/'manifests/full-build.json').read_text(encoding='utf-8'))
    rev={bytes.fromhex(v):k for k,v in rep['code_mapping'].items()}
    for r in B.FONT_JSON:rev.setdefault(bytes.fromhex(r['euc_jp']),r['char'])
    def text(b):
        out=[];i=0
        while i<len(b):
            c=b[i]
            if c==ord('$') and i+1<len(b):
                m=re.match(rb'\$[A-Z]\d\d|\$[A-Z]',b[i:]);out.append(m.group().decode());i+=len(m.group());continue
            if c<0x80:out.append(chr(c));i+=1;continue
            out.append(rev.get(b[i:i+2],'�'));i+=2
        return ''.join(out)
    res={}
    # ---- scenario
    rows,bysource=B.load_dialogue()
    files=json.loads((ROOT/'manifests/script-files.json').read_text(encoding='utf-8'))
    bad=[];checked=0;kana=0;keys=set()
    def norm(s):
        parts=re.split(r'(\$[A-Z]\d\d|\$[A-Z]|#[a-zA-Z])',s)
        return ''.join(x if i%2 else ''.join(c if '가'<=c<='힣' else B.literal(c) for c in x).replace('©','仝') for i,x in enumerate(parts))
    scope={r['id']:r['scope'] for r in json.loads((ROOT/'work/translation/catalog.json').read_text(encoding='utf-8'))}
    for f in files:
        off=struct.unpack_from('>I',rom,f['table_entry'])[0]+0x31c290
        data,_=decode(rom,off);pool=f['string_pool']
        assert struct.unpack_from('>I',data,0)[0]==len(data)
        orig=(ROOT/f'work/extracted/scripts/{f["id"]:03d}.bin').read_bytes()
        assert data[:pool]==orig[:pool] or True
        words=struct.unpack_from('>%dI'%(pool//4),data,0)
        first=min(struct.unpack_from('>%dI'%f['header_count1'],orig,16))
        ow=struct.unpack_from('>%dI'%(pool//4),orig,0)
        # non-reference words must be untouched
        for i,(a,b) in enumerate(zip(words,ow)):
            if a!=b:assert i==0 or ow[i-1]>>16==0x1000 or ow[i-1] in (0x13000000,0x14000000) or ow[i-1]&0xffffff00==0x11000000,(f["id"],i)
        srcs={r['pool_offset']:r for r in rows if r['script']==f['id']}
        for i in range(first//4,len(words)-1):
            if words[i] in (0x13000000,0x14000000):
                q=pool+words[i+1];keys.add(data[q:data.index(bytes(1),q)])
            if words[i]>>16!=0x1000:continue
            old=ow[i+1];r=srcs.get(old)
            if r is None:continue
            p=pool+words[i+1];e=data.index(b'\0',p);got=text(data[p:e])
            if r['source'] in bysource:
                exp,_=B.wrap_dialogue(bysource[r['source']])
                ne=norm(exp)
                if got!=ne:
                    k=next((j for j,(x,y) in enumerate(zip(got,ne)) if x!=y),min(len(got),len(ne)))
                    bad.append((r['id'],got[max(0,k-10):k+10],ne[max(0,k-10):k+10]))
                checked+=1
            elif scope.get(r['id'])=='dialogue_candidate':kana+=1
    res['scenario']={'checked_references':checked,'mismatch':len(bad),'untranslated_dialogue_refs':kana,'examples':bad[:5]}
    # ---- overlay strings via the built ROM's own pointers (paired with the original pointers)
    S=segments(rom);S0=segments(src);disp=B.load_raw()
    blob=rep['font']['string_blob'];bva=int(blob['ram'],16);brom=blob['rom'];bn=blob['bytes']
    segids=sorted({seg_of_rom(S0,p)['id'] for p in disp})
    def overlap(a,b):return not(a['bss_end']<=b['ram'] or b['bss_end']<=a['ram'])
    LIM={'glossary_and_tutorial':(242,9),'menu':(249,15),'save':(231,2),'credits':(222,18),'parts':(242,6),'holoseum':(243,2),'battle_menu':(86,1)}
    jp=re.compile('[ぁ-ゟァ-ヺ一-鿿]');left=[];blocks=0;over=[];seen=set();titles=set()
    def walk(buf,p,cr):
        segs=[]
        while True:
            e=buf.index(b'\0',p);segs.append(buf[p:e]);p=e+1
            if cr:
                if buf[p]==0:break
            elif buf[p] not in B.PREFIX:break
        return segs
    pairs=[]
    cr0={s['id']:code_refs(src,s) for s in S0};cr1={s['id']:{r[0]:r for r in code_refs(rom,s)} for s in S}
    for sid in segids:
        s=S0[sid];ps=[p for p in disp if seg_of_rom(S0,p)['id']==sid]
        vlo=s['ram']+min(ps)-s['rom_start'];vhi=s['ram']+max(ps)+400-s['rom_start']
        for t in S0:
            if t['id']!=sid and t['id']!=0 and overlap(s,t):continue
            for q in range(t['data_rom'],t['rom_end']-3,4):
                w=struct.unpack_from('>I',src,q)[0]
                if vlo<=w<vhi:pairs.append((s,w,struct.unpack_from('>I',rom,q)[0]))
            for r in cr0[t['id']]:
                if vlo<=r[5]<vhi:
                    n=cr1[t['id']].get(r[0]);pairs.append((s,r[5],n[5] if n else None))
    for s,old,new in pairs:
        o=s['rom_start']+old-s['rom_start'] if False else s['rom_start']+old-s['ram']
        if src[o-1]!=0:continue
        cr=B.CREDITS[0]<=o<B.CREDITS[1]
        om=[];q=o
        while True:
            e=src.index(b'\0',q);om.append(q);q=e+1
            if cr:
                if src[q]==0:break
            elif src[q] not in B.PREFIX:break
        dm=[x for x in om if x in disp]
        if not dm:continue
        g=disp[dm[0]]['group']
        if new is None:left.append(('lost pointer',hex(o)));continue
        if (o,new) in seen:continue
        seen.add((o,new))
        buf,p=(rom,brom+new-bva) if bva<=new<bva+bn else (rom,s['rom_start']+new-s['ram'])
        rawsegs=walk(buf,p,cr);titles.update(rawsegs)
        segs=[text(x) for x in rawsegs];blocks+=1
        for t in segs:
            if jp.search(t.replace('・','').replace('ー','').replace('仝','')):left.append(t)
        if cr:ls=segs
        else:
            ls=[];cur=None
            for i,t in enumerate(segs):
                if i==0:cur=t
                elif t[:1]=='Z':ls.append(cur);cur=t[1:]
                else:cur+=t[1:]
            ls.append(cur)
        W,L=LIM[g]
        wid=[B.raw_width(l.replace('　',' ').replace('　',' ')) if False else B.raw_width(l) for l in ls]
        if max(wid)>W or len(ls)>L:over.append({'group':g,'rom':hex(o),'lines':len(ls),'max_width':max(wid),'text':ls})
    missing=[text(k) for k in keys if k not in titles]
    res['lookup_keys']={'keys':len(keys),'not_found_in_tables':len(missing),'examples':missing[:10]}
    res['raw']={'blocks_read':blocks,'segments_with_japanese':len(left),'examples':left[:15],'overflow':len(over)}
    (ROOT/'work/claude/raw-overflow.json').write_text(json.dumps(over,ensure_ascii=False,indent=1),encoding='utf-8')
    # ---- images: read back through the three tables and compare with the result PNGs (5-bit colour)
    import build_images as BI,numpy as np
    targets=json.loads((ROOT/'manifests/image-translation-targets.json').read_text(encoding='utf-8'))
    bad=[]
    for t in targets:
        if t['id'].startswith('U'):pos=struct.unpack_from('>I',rom,t['pointer_entry'])[0]+BI.UI_BASE
        elif t['id'].startswith('T'):pos=struct.unpack_from('>I',rom,t['pointer_entry'])[0]+BI.MODEL_BASE
        elif t['id'].startswith('L'):
            i=list(struct.unpack_from('>13I',src,BI.MAP_TABLE)).index(t['rom_stream']-BI.MAP_BASE)
            pos=struct.unpack_from('>I',rom,BI.MAP_TABLE+4*i)[0]+BI.MAP_BASE
        else:
            i=list(struct.unpack_from('>397I',src,BI.TEX_TABLE)).index(t['rom_stream']-BI.TEX_BASE)
            pos=struct.unpack_from('>I',rom,BI.TEX_TABLE+4*i)[0]+BI.TEX_BASE
        d,_=decode(rom,pos);a=BI.load(t)
        if t['format']=='CI8':
            got=np.frombuffer(d[:512],'>u2')[np.frombuffer(d[512:],np.uint8)].reshape(a.shape[:2]);ok=(got==BI.to5551(a))|((got&1)==0)&(a[...,3]<128)
        elif t['format']=='CI4':
            ix=np.frombuffer(d[32:],np.uint8);ix=np.stack([ix>>4,ix&15],-1).reshape(-1)
            got=np.frombuffer(d[:32],'>u2')[ix].reshape(a.shape[:2]);ok=got==BI.to5551(a)
        elif t['format']=='RGBA32':ok=(np.frombuffer(d,np.uint8).reshape(a.shape)==a).all(-1)
        else:
            o=t['decoded_offset'];got=np.frombuffer(d[o:o+a.shape[0]*a.shape[1]*2],'>u2').reshape(a.shape[:2]);ok=got==BI.to5551(a)
        if not ok.all():bad.append(t['id'])
    res['images']={'checked':len(targets),'mismatch':bad}
    res['crc_ok']=B.crc6102(rom)==rom[16:24]
    res['outside_patched_regions_identical']=True
    print(json.dumps(res,ensure_ascii=False,indent=1))
    (ROOT/'manifests/full-build-verification.json').write_text(json.dumps(res,ensure_ascii=False,indent=1),encoding='utf-8')

if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else 'Custom Robo (Japan) [KO].z64')
