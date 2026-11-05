"""Local emulator test through the documented Mupen64Plus frontend API.

Uses a project-local configuration, no desktop keyboard/mouse automation.
Input is delivered to the emulator API, never to another application.
"""
from pathlib import Path
import ctypes as C, os, sys, json, argparse, time, threading
ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--rom',default='build/Custom Robo (Japan) [KO opening probe].z64')
    ap.add_argument('--frames',type=int,default=600);ap.add_argument('--shots',default='150,300,590')
    ap.add_argument('--inputs',default='{}');ap.add_argument('--state');ap.add_argument('--save-state');ap.add_argument('--timeout',type=int,default=60)
    ap.add_argument('--ram4',action='store_true',help='Test without the Expansion Pak, in this project-local config')
    ap.add_argument('--diagnose-frame',type=int,default=0)
    args=ap.parse_args();exe=ROOT/'tools/mupen64plus/Release';runtime=ROOT/'work/runtime'
    runtime.mkdir(exist_ok=True);(runtime/'config').mkdir(exist_ok=True);(runtime/'screenshots').mkdir(exist_ok=True)
    data=(ROOT/args.rom).read_bytes();os.chdir(exe);dllpath=os.add_dll_directory(str(exe))
    core=C.CDLL(str(exe/'mupen64plus.dll'))
    debug_t=C.CFUNCTYPE(None,C.c_void_p,C.c_int,C.c_char_p)
    state_t=C.CFUNCTYPE(None,C.c_void_p,C.c_int,C.c_int)
    frame_t=C.CFUNCTYPE(None,C.c_uint)
    log=(runtime/'emulator.log').open('w',encoding='utf-8')
    @debug_t
    def debug(ctx,level,message):
        if level>4:return
        log.write(f'{level} {message.decode("utf-8",errors="replace")}\n');log.flush()
    @state_t
    def state(ctx,param,value):pass
    def bind(name,restype,*argtypes):
        fn=getattr(core,name);fn.restype=restype;fn.argtypes=list(argtypes);return fn
    def ok(result,where):
        if result:raise RuntimeError(f'{where}: Mupen64Plus error {result}')
    startup=bind('CoreStartup',C.c_int,C.c_int,C.c_char_p,C.c_char_p,C.c_void_p,debug_t,C.c_void_p,state_t)
    command=bind('CoreDoCommand',C.c_int,C.c_int,C.c_int,C.c_void_p)
    attach=bind('CoreAttachPlugin',C.c_int,C.c_int,C.c_void_p)
    section=bind('ConfigOpenSection',C.c_int,C.c_char_p,C.POINTER(C.c_void_p))
    setparam=bind('ConfigSetParameter',C.c_int,C.c_void_p,C.c_char_p,C.c_int,C.c_void_p)
    def config(group,key,value):
        handle=C.c_void_p();ok(section(group.encode(),C.byref(handle)),'open section')
        if isinstance(value,str):kind=4;ptr=C.c_char_p(value.encode())
        else:kind=3 if isinstance(value,bool) else 1;val=C.c_int(value);ptr=C.byref(val)
        ok(setparam(handle,key.encode(),kind,ptr),'set parameter')
    ok(startup(0x020001,b'../../../work/runtime/config',b'.',None,debug,None,state),'startup')
    for key,value in {'OnScreenDisplay':False,'ScreenshotPath':'../../../work/runtime/screenshots',
                       'SaveStatePath':'../../../work/runtime','SaveSRAMPath':'../../../work/runtime',
                       'R4300Emulator':2,'DisableExtraMem':args.ram4}.items():config('Core',key,value)
    config('Video-General','Fullscreen',False);config('Video-General','ScreenWidth',640);config('Video-General','ScreenHeight',480)
    rom=C.create_string_buffer(data);ok(command(1,len(data),rom),'ROM open')
    for key,value in {'mode':0,'device':-1,'plugged':True,'plugin':2,'Start':'key(13)','A Button':'key(120)',
                      'B Button':'key(99)','L Trig':'key(113)','R Trig':'key(101)','X Axis':'key(276,275)','Y Axis':'key(273,274)'}.items():config('Input-SDL-Control1',key,value)
    for i in range(2,5):
        config(f'Input-SDL-Control{i}','mode',0)
        config(f'Input-SDL-Control{i}','device',-1)
        config(f'Input-SDL-Control{i}','plugged',False)
    plugins=[]
    for kind,name in [(2,'video-glide64mk2'),(3,'audio-sdl'),(4,'input-sdl'),(1,'rsp-hle')]:
        plugin=C.CDLL(str(exe/f'mupen64plus-{name}.dll'))
        plugin.PluginStartup.argtypes=[C.c_void_p,C.c_void_p,debug_t];plugin.PluginStartup.restype=C.c_int
        ok(plugin.PluginStartup(core._handle,None,debug),name+' startup');plugins.append((kind,plugin));ok(attach(kind,plugin._handle),'attach '+name)
    core.ConfigSaveFile()
    shots={int(v) for v in args.shots.split(',') if v};inputs={int(k):v for k,v in json.loads(args.inputs).items()};events=[]
    start=time.monotonic()
    cpu_ptr=bind('DebugGetCPUDataPtr',C.c_void_p,C.c_int)
    mem_ptr=bind('DebugMemGetPointer',C.c_void_p,C.c_int)
    def diagnose(label):
        snapshot={'pc':hex(C.c_uint32.from_address(cpu_ptr(1)).value),
                  'registers':[hex(v) for v in (C.c_uint64*32).from_address(cpu_ptr(2))],
                  'cop0':[hex(v) for v in (C.c_uint32*32).from_address(cpu_ptr(5))]}
        (runtime/f'diagnostic-{label}.json').write_text(json.dumps(snapshot,indent=2))
        raw=C.string_at(mem_ptr(1),0x400000 if args.ram4 else 0x800000)
        import array
        words=array.array('I');words.frombytes(raw);words.byteswap()
        (runtime/f'diagnostic-{label}-ram.bin').write_bytes(words.tobytes())
    @frame_t
    def frame(index):
        if args.diagnose_frame and index==args.diagnose_frame:diagnose(f'frame-{index}')
        if index in shots:command(16,0,None);events.append({'frame':index,'action':'screenshot'})
        if index in inputs:
            key,pressed=inputs[index]
            # SDL2 builds consume scancodes, while the input config stores SDL1 key symbols.
            scan={13:40,120:27,99:6,273:82,274:81,275:79,276:80}.get(key,key)
            ok(command(13 if pressed else 14,scan,None),'input');events.append({'frame':index,'key':key,'pressed':pressed})
        if args.save_state and index==args.frames-5:command(11,1,C.c_char_p(args.save_state.encode()))
        if index>=args.frames:command(6,0,None)
    ok(command(15,0,C.cast(frame,C.c_void_p)),'frame callback')
    if args.state:ok(command(10,0,C.c_char_p(args.state.encode())),'state load')
    finished=threading.Event()
    def watchdog():
        if not finished.wait(args.timeout):
            diagnose('timeout')
            events.append({'action':'watchdog_stop','reason':f'{args.timeout}-second test limit'})
            command(6,0,None)
    threading.Thread(target=watchdog,daemon=True).start()
    ok(command(5,0,None),'execute');finished.set()
    for kind,plugin in reversed(plugins):core.CoreDetachPlugin(kind);plugin.PluginShutdown()
    command(2,0,None);core.CoreShutdown();log.close()
    (runtime/'last-run.json').write_text(json.dumps({'rom':args.rom,'seconds':time.monotonic()-start,'requested_frames':args.frames,'events':events},indent=2))
    print('Run complete; see work/runtime/emulator.log and screenshots.')

if __name__=='__main__':main()
