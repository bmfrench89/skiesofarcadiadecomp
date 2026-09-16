import sys,pickle,collections,bisect
sys.path.insert(0,'tools')
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
M=pickle.load(open('scratch/gx/m2.pkl','rb'))
funcs=sorted(pickle.load(open(SCR+r'\skies_funcs.pkl','rb')));fstarts=[f[0] for f in funcs]
sdk={}
for ln in open(SCR+r'\skies_sdk_symbols.txt'):
    if ln.startswith('0x'):
        p=ln.split(); sdk[int(p[0],16)]=p[2]
def fn(a):
    i=bisect.bisect_right(fstarts,a)-1
    f=funcs[i]; return (f[0],sdk.get(f[0],f[2])) if f[0]<=a<f[0]+f[1] else (f[0],'~'+sdk.get(f[0],f[2]))
SDKLO,SDKHI=0x802319E0,0x80266770
for v in (0xCC000000,0xCC010000):
    ls=sorted(M['lis'][v])
    ins=[a for a in ls if SDKLO<=a<SDKHI]; out=[a for a in ls if not(SDKLO<=a<SDKHI)]
    print(f"\n=== lis 0x{v:08X}: {len(ls)} sites | inSDK {len(ins)} | outside {len(out)}")
    fc=collections.Counter(fn(a) for a in out)
    print("  outside-SDK functions:", len(fc))
    for (fa,nm),n in sorted(fc.items()):
        print(f"    0x{fa:08X} n={n:3d} {nm}")
