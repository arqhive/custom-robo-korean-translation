"""Decode the UI bank and publish Japanese-bearing translation targets only.
Dimensions of text-bearing entries were checked visually; effect-strip layouts
remain descriptive raw views and are not advertised as translation targets.
"""
import json, struct, html, shutil
import numpy as np
from PIL import Image
from survey_rom import ROOT
from extract_assets import rgba16

def main():
    rom=(ROOT/'Custom Robo (Japan).z64').read_bytes()
    guesses=json.loads((ROOT/'work/research/ui-auto.json').read_text())
    widths={53:160,54:160,55:160,56:160,57:160,58:160,109:16}
    out=ROOT/'work/extracted/ui';out.mkdir(exist_ok=True);entries=[];targets=[]
    labels={2:'커스텀 로보',3:'커스텀 로보',4:'커스텀 로보',5:'커스텀 로보',
      19:'로 (타이틀 조각)',20:'보 (타이틀 조각)',22:'커스텀 (타이틀 조각)',
      24:'아케이드 모드',25:'아케이드 모드',26:'시나리오 모드',27:'시나리오 모드',28:'옵션 모드',29:'옵션 모드',
      31:'스테이지 클리어',32:'스테이지 클리어',33:'프리 배틀',34:'프리 배틀',35:'VS 배틀',36:'VS 배틀',
      37:'기록 보기',38:'남은 에너지',39:'남은 시간',40:'점수',41:'총점',42:'퍼펙트',45:'초',47:'패배 페널티',48:'신기록!',
      54:'초급',55:'중급',56:'상급',57:'달인급',58:'전설급',
      59:'초급',60:'중급',61:'상급',62:'달인',63:'전설',64:'초급',65:'중급',66:'상급',67:'달인',68:'전설',
      106:'커스터마이즈 완료',114:'사용 안 함 / 점프 / 어택 / 건 / 봄 / 포드 / 이동 / 일시 정지'}
    for n,g in enumerate(guesses):
        offset=0x6d5300+struct.unpack_from('>I',rom,0x4f300+n*4)[0]
        raw=(ROOT/f'work/extracted/streams/{offset:08X}.bin').read_bytes()
        width=widths.get(n,g['width'])
        if g['format']=='CI8':
            pal=np.array(rgba16(raw[:512],256,1)).reshape(256,4)
            pixels=pal[np.frombuffer(raw[512:],dtype=np.uint8)];pixel_offset=512
        else:pixels=np.frombuffer(raw,dtype=np.uint8).reshape(-1,4);pixel_offset=0
        height=len(pixels)//width;im=Image.fromarray(pixels.reshape(height,width,4));path=out/f'U{n:03d}.png';im.save(path)
        e={'id':f'U{n:03d}','bank_index':n,'rom_stream':offset,'pointer_entry':0x4f300+n*4,
           'format':g['format'],'width':width,'height':height,'pixel_offset':pixel_offset,
           'file':str(path.relative_to(ROOT)),'translation_target':n in labels}
        entries.append(e)
        if n in labels:targets.append(dict(e,group='title' if n in [2,3,4,5,19,20,22] else 'instructions' if n==114 else 'menu',proposal=labels[n],flip_y=False,status='untranslated'))
    textures=json.loads((ROOT/'manifests/images-confirmed.json').read_text())
    signs={'0049D98C':'가라테부','004BB130':'공사 중','004C1074':'지역 예선','004C31FC':'지역 예선',
           '004C3770':'예선장','004CA554':'관계자 외 출입 금지','004CC10C':'선수 접수',
           '004CC7CC':'커스텀 로보 시민 대회','004CD3CC':'카린 파이팅','004D35E4':'그레이트 로보 컵'}
    for e in textures:
        key=f'{e["rom_stream"]:08X}'
        if key in signs:targets.append(dict(e,group='signs',proposal=signs[key],flip_y=True,status='untranslated'))
    places=['자택','로보 스테이션','학교','공원','메디컬 센터','시민회관','카트레아 저택','점보 사이트 동관','점보 사이트 서관','시범 경기장','노지마 빌딩','항구 창고','그레이트 로보 컵 돔']
    full=ROOT/'manifests/all-images.json'
    if full.exists():
        maps=[r for r in json.loads(full.read_text(encoding='utf-8')) if r['category']=='map-labels']
        assert len(maps)==len(places)
        for e,label in zip(maps,places):targets.append(dict(e,group='map',proposal=label,flip_y=False,status='untranslated'))
    (ROOT/'manifests/ui-images.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'manifests/image-translation-targets.json').write_text(json.dumps(targets,ensure_ascii=False,indent=2),encoding='utf-8')
    review=ROOT/'work/image-translation';review.mkdir(exist_ok=True)
    groups={'title':'타이틀 로고','menu':'모드·기록·등급','instructions':'조작 안내','signs':'배경 간판','map':'지도 지명'}
    parts=['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>커스텀로보 이미지 번역 대상</title>',
      '<style>body{background:#172029;color:#edf3f8;font:16px/1.6 system-ui;margin:30px auto;max-width:1250px;padding:0 20px}nav{position:sticky;top:0;background:#172029;padding:12px}a{color:#92d6ff;margin-right:20px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(285px,1fr));gap:18px}article{background:#25333f;border:1px solid #526470;border-radius:9px;overflow:hidden}article h3,article p{padding:0 16px}.art{height:250px;display:flex;align-items:center;justify-content:center;background:repeating-conic-gradient(#404d58 0% 25%,#485660 0% 50%) 0/20px 20px}.art img{max-width:96%;max-height:240px;image-rendering:pixelated}small{color:#afbfcb}</style>',
      f'<h1>커스텀로보 · 이미지 번역 대상</h1><p>일본어가 확인된 {len(targets)}개만 표시합니다. 아래 문구는 번역 초안이며 이미지는 아직 원본입니다. 배경 간판은 게임에서 읽는 방향으로 뒤집어 표시했습니다.</p>',
      '<p><small>전체 추출 이미지 4,286장 가운데 일본어가 확인된 번역 대상입니다. 미세한 무늬·판독 불가 포스터는 별도 판독이 필요합니다. 글꼴 1,646자는 별도 보관했습니다.</small></p>',
      '<nav>'+''.join(f'<a href="#{g}">{name}</a>' for g,name in groups.items())+'</nav>']
    for group,name in groups.items():
        parts.append(f'<h2 id="{group}">{name}</h2><div class="grid">')
        for e in targets:
            if e['group']!=group:continue
            src='../'+Path(e['file']).relative_to('work').as_posix();style='transform:scaleY(-1);' if e['flip_y'] else ''
            parts.append(f'<article><h3>{e["id"]} <small>{e["width"]}×{e["height"]}</small></h3><div class="art"><img src="{html.escape(src)}" style="{style}width:{e["width"]*2}px"></div><p>{html.escape(e["proposal"])}</p></article>')
        parts.append('</div>')
    parts.append('</html>');(review/'index.html').write_text(''.join(parts),encoding='utf-8')
    print(f'UI images: {len(entries)}; Japanese targets: {len(targets)}')

from pathlib import Path
if __name__=='__main__':main()
