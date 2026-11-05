"""Inventory every NUL-delimited Japanese string in scripts and other banks.

Raw binary candidates are kept separate from confirmed script pools. Candidates
must round-trip EUC-JP and use the game's glyph repertoire, including kanji-only
labels missed by the earlier kana-only survey.
"""
from pathlib import Path
import json,re,hashlib,collections
from survey_rom import ROOT

def parse(raw,codes,min_japanese=1):
    if not raw or len(raw)>8192:return None
    pos=0;japanese=0
    while pos<len(raw):
        c=raw[pos]
        if c in (9,10,13) or 32<=c<=126:pos+=1;continue
        if pos+1>=len(raw):return None
        code=c*256+raw[pos+1]
        if code not in codes:return None
        japanese+=1;pos+=2
    if japanese<min_japanese:return None
    try:s=raw.decode('euc_jp')
    except UnicodeDecodeError:return None
    if s.encode('euc_jp')!=raw:return None
    if not re.search('[ぁ-ヿ一-鿿]',s):return None
    return s

def spans(blob):
    start=0
    while True:
        end=blob.find(b'\0',start)
        if end<0:return
        if end>start:yield start,blob[start:end]
        start=end+1

def main():
    rom=(ROOT/'Custom Robo (Japan).z64').read_bytes()
    codepoints={int(r['euc_jp'],16) for r in json.loads((ROOT/'manifests/font.json').read_text(encoding='utf-8'))}
    streams=json.loads((ROOT/'manifests/compressed-streams.json').read_text())
    scripts=json.loads((ROOT/'manifests/script-files.json').read_text())
    script_offsets={r['rom_offset'] for r in scripts}
    excluded=[(r['offset'],r['offset']+r['stored_size']) for r in streams]
    excluded.append((0x1195a0,0x12095c))
    excluded.sort();merged=[]
    for start,end in excluded:
        if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else:merged.append((start,end))
    rawrows=[];cursor=0
    for start,end in merged+[(len(rom),len(rom))]:
        if cursor<start:
            for offset,b in spans(rom[cursor:start]):
                absolute=cursor+offset
                # The code/data section is known to contain actual text. Other
                # binary gaps need a stricter threshold and manual classification.
                s=parse(b,codepoints,1 if absolute<0x1195a0 else 4)
                if s is not None:
                    rawrows.append({'id':f'R{absolute:08X}','rom_offset':absolute,'bytes':len(b),'source':s,
                                    'translation':None,'scope':'raw_text_candidate' if absolute<0x1195a0 else 'binary_gap_candidate',
                                    'encoding':'euc_jp','roundtrip':True})
        cursor=max(cursor,end)
    embedded=[]
    for r in streams:
        if r['offset'] in script_offsets:continue
        blob=(ROOT/r['file']).read_bytes()
        for offset,b in spans(blob):
            s=parse(b,codepoints,4)
            if s is not None:
                embedded.append({'id':f'C{r["offset"]:08X}-{offset:06X}','rom_stream':r['offset'],
                                 'decoded_offset':offset,'bytes':len(b),'source':s,'translation':None,
                                 'scope':'compressed_binary_candidate','encoding':'euc_jp','roundtrip':True})
    originals=json.loads((ROOT/'work/translation/source-texts.json').read_text(encoding='utf-8'))
    allrows=originals+rawrows+embedded
    dest=ROOT/'work/translation';dest.mkdir(exist_ok=True)
    (dest/'raw-text-full.json').write_text(json.dumps(rawrows,ensure_ascii=False,indent=2),encoding='utf-8')
    (dest/'embedded-text-candidates.json').write_text(json.dumps(embedded,ensure_ascii=False,indent=2),encoding='utf-8')
    with (dest/'all-text-sources.jsonl').open('w',encoding='utf-8') as f:
        for row in allrows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    report={'rom_sha256':hashlib.sha256(rom).hexdigest(),'script_files':len(scripts),'script_strings':len(originals),
            'raw_strings':len(rawrows),'compressed_binary_candidates':len(embedded),'scanned_compressed_streams':len(streams),
            'all_source_strings':len(allrows),'all_unique_sources':len({r['source'] for r in allrows}),
            'kanji_only_included':True,'all_accepted_strings_encoding_roundtrip':True,
            'candidate_classification_complete':False,'non_nul_or_non_euc_jp_text_formats':'require separate format audit'}
    (ROOT/'manifests/full-text-extraction.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
