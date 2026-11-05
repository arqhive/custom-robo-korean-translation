"""Show how overflowing description blocks lay out (width px / line count) with candidate edits.
usage: python -X utf8 check_raw_fit.py <packet.json> [<candidates.json {id: text}>]"""
import json,sys
import build_full as B
pk=json.load(open(sys.argv[1],encoding='utf-8'))
cand=json.load(open(sys.argv[2],encoding='utf-8')) if len(sys.argv)>2 else {}
bad=0
for b in pk:
    segs=[];prev=''
    for i,s in enumerate(b['segments']):
        t=cand.get(s['id'],s['translation']) if s['id'] else None
        if t is None:t=s['source'].replace('、',',').replace('。','.') if i else s['source']
        else:t=B._join_space(prev,t)
        segs.append(t);prev=t
    try:new=B.reflow_block(segs,b['max_width'])
    except AssertionError as e:print(b['rom'],'UNBREAKABLE LINE',e);bad+=1;continue
    lines=[];cur=None
    for i,t in enumerate(new):
        if i==0:cur=t
        elif t[:1]=='Z':lines.append(cur);cur=t[1:]
        else:cur+=t[1:]
    lines.append(cur)
    ok=len(lines)<=b['max_lines'] and max(B.raw_width(l) for l in lines)<=b['max_width']
    bad+=not ok
    print(('OK ' if ok else 'OVER'),b['rom'],f"{len(lines)}/{b['max_lines']} lines")
    for l in lines:print('   ',B.raw_width(l),l)
print('blocks over limit:',bad)
