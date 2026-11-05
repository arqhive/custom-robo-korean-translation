"""Merge reviewed scenario batches; validate controls and prepare a review page."""
from pathlib import Path
import json,re,html,hashlib,collections
ROOT=Path(__file__).resolve().parents[1]
CONTROL=re.compile(r'\$(?:[A-Z]\d{2}|[A-Z])|#[a-zA-Z]')

def tokens(s):return [x for x in CONTROL.split(s)]

def literal(c):
    if c=='~':return '〜'
    if c=='·':return '・'
    if c==' ':return '\u3000'
    if c=="'":return '’'
    if c=='"':return '”'
    if 0x21<=ord(c)<=0x7e:return chr(ord(c)+0xfee0)
    return c

def encode_text(s,mapping):
    out=[];pos=0
    for m in CONTROL.finditer(s):
        for c in s[pos:m.start()]:
            c=literal(c);b=mapping[c] if c in mapping else c.encode('euc_jp')
            assert len(b)==2,repr(c)
            out.append(b)
        out.append(m.group().encode('ascii'));pos=m.end()
    for c in s[pos:]:
        c=literal(c);b=mapping[c] if c in mapping else c.encode('euc_jp')
        assert len(b)==2,repr(c)
        out.append(b)
    return b''.join(out)

def collect():
    rows=json.loads((ROOT/'work/translation/source-texts.json').read_text(encoding='utf-8'))
    byid={r['id']:r for r in rows};translations={}
    paths=[ROOT/'work/translation/opening-ko.json',*sorted((ROOT/'work/translation').glob('scenario-*-ko.json'))]
    for p in paths:
        for ident,text in json.loads(p.read_text(encoding='utf-8')).items():
            assert ident in byid and ident not in translations,ident
            assert CONTROL.findall(text)==CONTROL.findall(byid[ident]['source']),ident
            assert not re.search('[ぁ-ヿ一-鿿]',text),ident
            translations[ident]=text
    bysource={}
    for ident,text in translations.items():
        source=byid[ident]['source']
        assert source not in bysource or bysource[source]==text,('inconsistent duplicate',ident)
        bysource[source]=text
    glyphs=sorted({c for text in translations.values() for c in text if '가'<=c<='힣'})
    assert len(glyphs)<=3008
    mapping={c:bytes([0x81+i//94,0xa1+i%94]) for i,c in enumerate(glyphs)}
    pending=[];changed=[];debug=False;last=None;classified=[]
    for r in rows:
        if r['script']!=last:debug=False;last=r['script']
        if r['source']=='全台詞':debug=True
        scope='debug_section' if debug else 'dialogue_candidate' if r['kind']=='dialogue' else 'label_or_internal_unresolved'
        row=dict(r,scope=scope,translation=bysource.get(r['source']))
        if row['translation'] is not None:
            b=encode_text(row['translation'],mapping)
            row['translated_bytes']=len(b)
            row['byte_budget_ok']=len(b)<=row['bytes']
            if not row['byte_budget_ok']:pending.append({'id':r['id'],'translated_bytes':len(b),'original_bytes':r['bytes']})
            changed.append(row)
        classified.append(row)
    report={'directly_translated_entries':len(translations),'translated_unique_sources':len(bysource),
            'translated_occurrences_including_duplicates':len(changed),'hangul_glyphs':len(glyphs),
            'controls_preserved':True,'all_literals_two_bytes':True,'byte_budget_failures':pending,
            'scope_counts':dict(collections.Counter(r['scope'] for r in classified)),
            'completed_dialogue_sections':[],
            'max_distinct_hangul_per_message':max(len(set(c for c in v if '가'<=c<='힣')) for v in translations.values()),
            'status':'partial_translation','unresolved_labels_are_not_automatically_translated':True}
    for n in range(79):
        candidates=[r for r in classified if r['script']==n and r['scope']=='dialogue_candidate']
        if candidates and all(r['translation'] is not None for r in candidates):report['completed_dialogue_sections'].append(n)
    if all(r['translation'] is not None for r in classified if r['scope']=='dialogue_candidate'):
        report['status']='scenario_translation_draft_complete'
    return classified,changed,mapping,report

def main():
    rows,changed,mapping,report=collect()
    (ROOT/'work/translation/catalog.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'manifests/translation-progress.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    dest=ROOT/'work/translation-review';dest.mkdir(exist_ok=True)
    def show(s):
        return re.sub(r'(\$(?:[A-Z]\d{2}|[A-Z])|#[a-zA-Z])',lambda m:'<span class="code">'+m[0]+'</span>'+('<br>' if m[0] in ('$R','$P') else ''),html.escape(s))
    cards=[];seen=set()
    for r in changed:
        if r['scope']!='dialogue_candidate' or r['source'] in seen:continue
        seen.add(r['source'])
        cards.append(f'<article><h3>{r["id"]}</h3><div class="pair"><div lang="ja">{show(r["source"])}</div><div lang="ko">{show(r["translation"])}</div></div></article>')
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>커스텀로보 — 초반 대사 번역</title><style>body{background:#18212a;color:#e9eef5;font:16px/1.65 system-ui;margin:32px auto;max-width:1200px;padding:0 22px}h1{font-size:26px}p{color:#bdcbd6}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}.pair>div{background:#24313e;padding:18px;border-radius:8px;overflow-wrap:anywhere}article{margin:26px 0}.code{color:#72a7b0;font-size:11px;margin:0 2px}h3{font-size:14px;color:#a8cce3}@media(max-width:750px){.pair{grid-template-columns:1fr}}</style><h1>커스텀로보 · 초반 대사</h1><p>도입부 → 스테이션 → 첫 배틀 → 카린과의 만남 → 학교·리히트. 왼쪽은 원문, 오른쪽은 번역입니다. 작은 코드는 줄바꿈·표정·버튼·선택지 등 게임 명령입니다. 전체 번역은 진행 중이며, 아래 항목은 게임 삽입 전/후 검증 기록과 별도로 관리합니다.</p>'''+''.join(cards)+'</html>'
    page=page.replace('초반 대사 번역','대사 번역').replace('초반 대사</h1>','대사 번역</h1>').replace('도입부 → 스테이션 → 첫 배틀 → 카린과의 만남 → 학교·리히트. ',f'번역된 고유 원문 {len(seen):,}항목. ')
    (dest/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='byte_budget_failures'}|{'entries_requiring_repacking':len(report['byte_budget_failures'])},ensure_ascii=False))

if __name__=='__main__':main()
