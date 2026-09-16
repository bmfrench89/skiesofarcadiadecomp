import sys,pickle,collections,bisect
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
calls,callers=pickle.load(open('scratch/gx/cg.pkl','rb'))
funcs=sorted(pickle.load(open(SCR+r'\skies_funcs.pkl','rb')))
Z=[('init',0x80003100,0x80005600),('game',0x80005600,0x802319E0),
   ('SDK',0x802319E0,0x80266778),('post',0x80266778,0x802AC7E0)]
def zone(a):
    for n,lo,hi in Z:
        if lo<=a<hi: return n
    return 'out'
cnt=collections.Counter(zone(f[0]) for f in funcs)
sz=collections.Counter()
for f in funcs: sz[zone(f[0])]+=f[1]
print("functions / bytes per zone:")
for n,_,_ in Z: print("   %-5s %5d funcs  %9d bytes"%(n,cnt[n],sz[n]))
M=collections.Counter()
for c,tg in calls.items():
    for t,n in tg.items(): M[(zone(c),zone(t))]+=n
print("\ncall-edge matrix (caller-zone -> callee-zone), call sites:")
zs=[n for n,_,_ in Z]
print("            "+"".join("%>10s"%z for z in zs).replace('%>10s','%10s')%tuple(zs) if False else "         "+" ".join("%8s"%z for z in zs))
for a in zs:
    print("   %-6s"%a+" ".join("%8d"%M[(a,b)] for b in zs))
# post-SDK sub-clusters
post=[f for f in funcs if 0x80266778<=f[0]<0x802AC7E0]
print("\npost-SDK functions:",len(post),"span 0x%08X-0x%08X"%(post[0][0],post[-1][0]))
# gaps
gaps=[]
for i in range(1,len(post)):
    g=post[i][0]-(post[i-1][0]+post[i-1][1])
    if g>256: gaps.append((post[i-1][0]+post[i-1][1],post[i][0],g))
print("gaps >256 bytes inside post-SDK:",len(gaps))
for a,b,g in gaps[:20]: print("   0x%08X-0x%08X (%d)"%(a,b,g))
# how much of post-SDK is only reachable from game
onlypost=sum(1 for f in post if all(zone(c)=='post' for c in callers.get(f[0],{})))
print("post-SDK funcs called ONLY from post-SDK:",onlypost)
print("post-SDK funcs with no callers:",sum(1 for f in post if not callers.get(f[0])))
