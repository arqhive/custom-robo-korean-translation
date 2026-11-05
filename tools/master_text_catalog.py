"""Join scenario and raw text translations without modifying event identifiers."""
from pathlib import Path
import json,re,collections,html
from survey_rom import ROOT
from translation_catalog import collect,CONTROL

def raw_translations(raw):
    byid={r['id']:r for r in raw};by_source={};direct={}
    for p in sorted((ROOT/'work/translation').glob('raw-*-ko.json')):
        for key,value in json.loads(p.read_text(encoding='utf-8')).items():
            assert key in byid and key not in direct,key
            source=byid[key]['source']
            assert CONTROL.findall(source)==CONTROL.findall(value),key
            assert re.findall(r'%[-+ #0]*\d*(?:\.\d+)?[sdxXuif]',source)==re.findall(r'%[-+ #0]*\d*(?:\.\d+)?[sdxXuif]',value),key
            if source[:1] in 'KLMNZHI':assert value.startswith(source[0]),key
            assert not re.search('[ぁ-ゟァ-ヺ一-鿿]',value),key
            assert source not in by_source or by_source[source]==value,('duplicate',key)
            by_source[source]=value;direct[key]=value
    terms=json.loads((ROOT/'work/translation/terms-ko.json').read_text(encoding='utf-8'))
    for suffix,ko in [('ポッド','포드'),('ボム','봄'),('ガン','건'),('レッグ','레그')]:
        for term in list(terms):
            if not term.endswith(('ポッド','ボム','ガン','レッグ')):terms.setdefault(term+suffix,terms[term]+' '+ko)
    def lookup(s):
        if s in by_source:return by_source[s]
        if s in terms:return terms[s]
        if s and s[:1] in 'KLMNZHI':
            rest=lookup(s[1:])
            if rest is not None:return s[0]+rest
        m=re.fullmatch(r'(#I|#T)?(.+?)(#[A-Z])?',s)
        if m and m[2] in terms:return (m[1] or '')+terms[m[2]]+(m[3] or '')
        return None
    return {r['id']:lookup(r['source']) for r in raw},direct

def main():
    scenario,_,_,sr=collect()
    raw=json.loads((ROOT/'work/translation/raw-text-full.json').read_text(encoding='utf-8'))
    data_ranges=[(0x43f90,0x566b0),(0x5a640,0x5eb80),(0x61620,0x61ba0),(0x69e60,0x6bec0),
        (0x814d0,0x9dd30),(0x9dea0,0x9dee0),(0xae3c0,0xc4410),(0xf1240,0xfd850),
        (0x112000,0x1157a0),(0x118a90,0x1195a0)]
    for r in raw:
        p=r['rom_offset']
        r['scope']='asset_internal_label' if p>=0x1195a0 else 'overlay_data_text_candidate' if any(a<=p<b for a,b in data_ranges) else 'machine_code_or_font_table'
    translations,direct=raw_translations(raw)
    display_ranges=[(0x5bd20,0x5eb80,'glossary_and_tutorial'),(0xb9ba0,0xc1234,'parts'),
        (0xc2174,0xc3978,'holoseum'),(0x113df0,0x1157a0,'menu'),
        (0x9d530,0x9d7f8,'save'),(0x9d873,0x9dd30,'credits'),
        (0xfcac0,0xfcb40,'battle_menu')]
    preserved_keys={'ウィンドウクローズ','ウィンドウオープン','ウインドウオープン','バトルポーズ音',
        '決定ボタン音','決定キャンセル','選択画面オープン','カウント','ブザー音','パーツ２個め','男ジャンプ','カウントダウン','Ａゲームオーバー','チャイムの音'}
    for r in raw:
        p=r['rom_offset'];r['translation']=None;r['group']=None
        if r['scope']=='machine_code_or_font_table':r['scope']='nontext_code_or_table'
        elif r['scope']=='asset_internal_label':r['scope']='internal_asset_identifier'
        else:r['scope']='debug_or_internal_identifier'
        for start,end,group in display_ranges:
            if start<=p<end:r['scope']='display_text';r['group']=group;break
        if p in (0x993c0,0x99418,0x99420):r['scope']='display_text';r['group']='menu'
        if 0x114fc0<=p<0x11527c:r['scope']='name_input_character_table'
        if r['source'].startswith('Ｂ') or r['source'] in preserved_keys or 0x1145e0<=p<0x11466c:
            if r['scope']=='display_text':r['scope']='internal_resource_identifier'
        if r['scope']=='display_text':
            r['translation']=translations[r['id']]
            r['application_policy']='relocate_display_string_with_references'
        else:r['application_policy']='preserve_original'
    embedded=json.loads((ROOT/'work/translation/embedded-text-candidates.json').read_text(encoding='utf-8'))
    for r in embedded:r['scope']='nontext_binary_coincidence'
    rows=scenario+raw+embedded
    (ROOT/'work/translation/raw-text-classified.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
    out=ROOT/'work/translation/master-texts.json'
    out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    pending=[r for r in scenario if r['scope']=='dialogue_candidate' and r['translation'] is None]
    raw_pending=[r for r in raw if r['scope']=='display_text' and r['translation'] is None]
    report={'source_occurrences':len(rows),'source_unique':len({r['source'] for r in rows}),
        'scenario_dialogue_occurrences':sr['scope_counts']['dialogue_candidate'],
        'scenario_dialogue_pending':len(pending),'scenario_dialogue_translation_complete':not pending,
        'raw_display_occurrences':sum(r['scope']=='display_text' for r in raw),
        'raw_translated_occurrences':sum(r['translation'] is not None for r in raw),
        'raw_pending':len(raw_pending),'raw_pending_ids':[r['id'] for r in raw_pending],
        'raw_scope_counts':dict(collections.Counter(r['scope'] for r in raw)),
        'raw_direct_entries':len(direct),'raw_classification_complete':True,
        'translation_draft_complete':not pending and not raw_pending,
        'unverified_credit_name_readings':5,
        'translation_complete':not pending and not raw_pending,
        'translation_status':'draft_pending_visual_and_name_review',
        'game_insertion_status':'not_built_for_full_translation'}
    (ROOT/'manifests/master-text-progress.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    extraction=ROOT/'manifests/full-text-extraction.json'
    er=json.loads(extraction.read_text(encoding='utf-8'))
    er.update(candidate_classification_complete=True,display_occurrences=report['scenario_dialogue_occurrences']+report['raw_display_occurrences'],classification_manifest='manifests/master-text-progress.json',embedded_candidates_confirmed_nontext=len(embedded))
    extraction.write_text(json.dumps(er,ensure_ascii=False,indent=2),encoding='utf-8')
    # A portable UTF-8 review/export for all display text, excluding symbols.
    display=[r for r in rows if r['scope'] in ('dialogue_candidate','display_text')]
    (ROOT/'work/translation/display-texts-ko.json').write_text(json.dumps(display,ensure_ascii=False,indent=2),encoding='utf-8')
    with (ROOT/'work/translation/display-texts-ko.jsonl').open('w',encoding='utf-8') as f:
        for r in display:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    dest=ROOT/'work/translation-review';dest.mkdir(exist_ok=True)
    seen=set();unique=[]
    for r in display:
        if (r['scope'],r['source']) in seen:continue
        seen.add((r['scope'],r['source']))
        unique.append({'id':r['id'],'group':r.get('group') or 'scenario','source':r['source'],'translation':r['translation']})
    payload=json.dumps(unique,ensure_ascii=False).replace('</','<\\/')
    page=r'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>커스텀 로보 전체 텍스트 번역</title><style>body{background:#18212a;color:#eaf1f8;font:16px/1.65 system-ui;max-width:1280px;margin:30px auto;padding:0 22px}header{position:sticky;top:0;background:#18212a;padding:10px 0}input,select,button{font:inherit;padding:7px;margin-right:10px}article{border-top:1px solid #506070;padding:16px 0}h3{font-size:13px;color:#a8cce3}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}.pair>div{background:#24313e;padding:16px;white-space:pre-wrap;overflow-wrap:anywhere}.code{color:#72a7b0;font-size:11px}a{color:#98d5ff}@media(max-width:750px){.pair{grid-template-columns:1fr}}</style><h1>커스텀 로보 · 전체 텍스트 번역 초안</h1><p>실제 표시 문구만 모았습니다. 본편·메뉴·용어집·튜토리얼·파츠·스테이지·저장 안내·크레딧을 포함합니다. 원본의 게임 명령은 작은 색 글자로 표시합니다. 게임 삽입·화면 줄맞춤은 다음 단계이며 크레딧 인명 5명의 읽기는 추가 확인이 필요합니다.</p><p><a href="../image-translation/index.html">일본어 이미지 번역 대상 68개</a></p><header><select id="group"><option value="">전체</option><option value="scenario">본편 대사</option><option value="glossary_and_tutorial">용어집·튜토리얼</option><option value="parts">파츠 설명</option><option value="holoseum">홀로세움</option><option value="menu">메뉴</option><option value="save">저장 안내</option><option value="credits">크레딧</option><option value="battle_menu">배틀 메뉴</option></select><input id="query" placeholder="원문·번역·ID 검색"><span id="count"></span></header><main></main><button id="more">더 보기</button><script>const rows=PAYLOAD;let filtered=[],limit=60;const main=document.querySelector('main');function esc(s){return s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}function show(s){return esc(s??'미번역').replace(/(\$(?:[A-Z]\d{2}|[A-Z])|#[a-zA-Z])/g,m=>'<span class="code">'+m+'</span>'+(['$R','$P'].includes(m)?'<br>':''))}function render(){main.innerHTML=filtered.slice(0,limit).map(r=>'<article><h3>'+r.id+' · '+r.group+'</h3><div class="pair"><div lang="ja">'+show(r.source)+'</div><div lang="ko">'+show(r.translation)+'</div></div></article>').join('');document.querySelector('#count').textContent=filtered.length+'개';document.querySelector('#more').hidden=limit>=filtered.length}function filter(){const g=document.querySelector('#group').value,q=document.querySelector('#query').value.toLowerCase();filtered=rows.filter(r=>(!g||r.group===g)&&[r.id,r.source,r.translation??''].join(' ').toLowerCase().includes(q));limit=60;render()}document.querySelector('#group').onchange=filter;document.querySelector('#query').oninput=filter;document.querySelector('#more').onclick=()=>{limit+=60;render()};filter();</script></html>'''.replace('PAYLOAD',payload)
    (dest/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
