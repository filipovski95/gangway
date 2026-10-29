# Draws the Plume icon (classic quill feather) and writes every Android size.
# Usage: python3 tools/make_icons.py
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
import math
S=1024; K=3
PLUM=(0x4B,0x22,0x70); PLUM2=(0x8A,0x4C,0xC4); DEEP=(0x2A,0x0F,0x45); LIME=(0xD8,0xF2,0x64); INK=(0x2E,0x12,0x48); CREAM=(0xF7,0xF3,0xEE); WHITE=(255,255,255)
def lerp(a,b,t): return tuple(int(a[i]+(b[i]-a[i])*t) for i in range(len(a)))
def grad_bg(size, c1=PLUM2, c2=PLUM, c3=DEEP):
    n=128; im=Image.new("RGB",(n,n)); px=im.load()
    for y in range(n):
        for x in range(n):
            t=min(1,math.hypot(x-n,y)/(n*1.35))
            px[x,y]=lerp(c1,c2,t/0.55) if t<0.55 else lerp(c2,c3,(t-0.55)/0.45)
    return im.resize((size,size),Image.BICUBIC)
def bez(p,t):
    a=(1-t)**3;b=3*(1-t)**2*t;c=3*(1-t)*t**2;d=t**3
    return (a*p[0][0]+b*p[1][0]+c*p[2][0]+d*p[3][0], a*p[0][1]+b*p[1][1]+c*p[2][1]+d*p[3][1])
def bezd(p,t):
    return (3*(1-t)**2*(p[1][0]-p[0][0])+6*(1-t)*t*(p[2][0]-p[1][0])+3*t**2*(p[3][0]-p[2][0]),
            3*(1-t)**2*(p[1][1]-p[0][1])+6*(1-t)*t*(p[2][1]-p[1][1])+3*t**2*(p[3][1]-p[2][1]))

def feather(size, color=LIME, spine=INK, tail=None, scale=1.0, style="split", vane_start=0.20, wl0=0.105, wr0=0.085, splits=((0.42,'l'),(0.63,'r'),(0.74,'l')), down=True, cx=0.5, cy=0.5, curve=1.0):
    """Long slim feather. style: 'split' (solid vane with barb splits), 'barbs' (made of stripes), 'outline' (line art)."""
    tail = tail or color
    W=size*K; u=W*scale; ox,oy=W*cx,W*cy
    P=lambda x,y:(ox+x*u, oy+y*u)
    sp=[(-0.30,0.30),(-0.12,0.08*curve+0.02*(1-curve)),(0.08,-0.10*curve-0.02*(1-curve)),(0.31,-0.31)]
    mask=Image.new("L",(W,W),0); md=ImageDraw.Draw(mask)
    N=200; L=[];R=[];frames=[]
    def width(tt,w0,p):
        # slim, widest a bit below the middle, long pointed tip, rounded base
        return w0*(math.sin(math.pi*min(1,tt)**p)**0.85)
    for i in range(N+1):
        t=i/N; x,y=bez(sp,t); dx,dy=bezd(sp,t); l=math.hypot(dx,dy); tx,ty=dx/l,dy/l; nx,ny=-ty,tx
        frames.append((t,x,y,tx,ty,nx,ny))
        if t<vane_start: continue
        tt=(t-vane_start)/(1-vane_start)
        wl=width(tt,wl0,0.80); wr=width(tt,wr0,0.75)
        L.append(P(x+nx*wl,y+ny*wl)); R.append(P(x-nx*wr,y-ny*wr))
    if style=="split":
        md.polygon(L+R[::-1], fill=255)
    if style=="outline":
        ring=L+R[::-1]+[L[0]]
        md.line(ring, fill=255, width=max(1,int(0.020*u)), joint="curve")
        # a few long barb lines inside the outline
        for i in range(0,N+1,14):
            t,x,y,tx,ty,nx,ny=frames[i]
            if t<vane_start+0.06 or t>0.88: continue
            tt=(t-vane_start)/(1-vane_start)
            for s_,w0 in ((1,wl0),(-1,wr0)):
                w=width(tt,w0,0.8); ang=math.radians(50)
                bx,by=s_*nx*math.cos(ang)+tx*math.sin(ang), s_*ny*math.cos(ang)+ty*math.sin(ang)
                ln=w/math.cos(ang)
                md.line([P(x+bx*ln*0.15,y+by*ln*0.15),P(x+bx*ln*0.78,y+by*ln*0.78)], fill=255, width=max(1,int(0.010*u)))
    if style=="barbs":
        # vane built from angled stripes (barbs) leaving the spine toward the tip
        for i in range(0,N+1,1):
            t,x,y,tx,ty,nx,ny=frames[i]
            if t<vane_start or t>0.985: continue
            tt=(t-vane_start)/(1-vane_start)
            for side,w0,p in ((1,wl0,0.80),(-1,wr0,0.75)):
                w=width(tt,w0,p)
                if w<0.004: continue
                ang=math.radians(48)
                bx,by=side*nx*math.cos(ang)+tx*math.sin(ang), side*ny*math.cos(ang)+ty*math.sin(ang)
                ln=w/math.cos(ang)
                if i%6 in (0,1,2,3):
                    md.line([P(x,y),P(x+bx*ln,y+by*ln)], fill=255, width=max(1,int(0.0065*u)))
    if style=="split":
        # splits: notches where barbs separate, angled toward the tip
        for (c,side) in splits:
            j=int(N*(vane_start+(1-vane_start)*c)); t,x,y,tx,ty,nx,ny=frames[j]
            tt=c; s=1 if side=='l' else -1
            w=width(tt,wl0 if side=='l' else wr0,0.8)
            ang=math.radians(50)
            bx,by=s*nx*math.cos(ang)+tx*math.sin(ang), s*ny*math.cos(ang)+ty*math.sin(ang)
            ln=w/math.cos(ang)
            a=(x+bx*ln*0.30,y+by*ln*0.30); b=(x+bx*ln*1.5,y+by*ln*1.5)
            # a thin wedge: narrow inside, wider at the edge
            wid=0.010
            px_,py_=-by,bx
            md.polygon([P(a[0],a[1]),P(b[0]+px_*wid,b[1]+py_*wid),P(b[0]-px_*wid,b[1]-py_*wid)], fill=0)
        # fine barb texture lines (subtle, cut into the vane)
        for i in range(0,N+1,9):
            t,x,y,tx,ty,nx,ny=frames[i]
            if t<vane_start+0.08 or t>0.9: continue
            tt=(t-vane_start)/(1-vane_start)
            for s,w0 in ((1,wl0),(-1,wr0)):
                w=width(tt,w0,0.8); ang=math.radians(50)
                bx,by=s*nx*math.cos(ang)+tx*math.sin(ang), s*ny*math.cos(ang)+ty*math.sin(ang)
                ln=w/math.cos(ang)
                md.line([P(x+bx*ln*0.35,y+by*ln*0.35),P(x+bx*ln*0.80,y+by*ln*0.80)], fill=0, width=max(1,int(0.0045*u)))
    if down:
        # soft downy fluff at the base of the vane
        for k,(c,s,ang,ln) in enumerate([(0.0,1,62,0.07),(0.035,1,58,0.085),(0.07,1,54,0.07),(0.01,-1,64,0.06),(0.045,-1,58,0.075),(0.08,-1,52,0.06)]):
            t0=vane_start-0.005+c; j=int(N*t0); t,x,y,tx,ty,nx,ny=frames[j]
            a=math.radians(ang); bx,by=s*nx*math.cos(a)+tx*math.sin(a), s*ny*math.cos(a)+ty*math.sin(a)
            # straight, tapering wisp
            for q in range(10):
                f0=q/10; f1=(q+1)/10
                md.line([P(x+bx*ln*f0,y+by*ln*f0),P(x+bx*ln*f1,y+by*ln*f1)], fill=255, width=max(1,int(0.009*u*(1-0.75*f0))))
    layer=Image.new("RGBA",(W,W),color+(0,)); layer.putalpha(mask)
    d=ImageDraw.Draw(layer)
    sp_pts=[P(*bez(sp,i/120)) for i in range(121)]
    vs=int(120*vane_start)
    d.line(sp_pts[vs:int(120*0.95)], fill=spine+(255,), width=max(1,int(0.012*u)), joint="curve")
    d.line(sp_pts[:vs+2], fill=tail+(255,), width=max(1,int(0.020*u)), joint="curve")
    x,y=sp_pts[0]; r=0.010*u; d.ellipse([x-r,y-r,x+r,y+r], fill=tail+(255,))
    return layer.resize((size,size),Image.LANCZOS)


import os
ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","brand")
def full_icon(size=S):
    im=grad_bg(size).convert("RGBA"); im.alpha_composite(feather(size, scale=1.30, style="split")); return im
def rounded(im, frac):
    s=im.size[0]; m=Image.new("L",(s*4,s*4),0); ImageDraw.Draw(m).rounded_rectangle([0,0,s*4-1,s*4-1],radius=int(s*4*frac),fill=255)
    out=im.convert("RGBA"); out.putalpha(m.resize((s,s),Image.LANCZOS)); return out
def circle(im):
    s=im.size[0]; m=Image.new("L",(s*4,s*4),0); ImageDraw.Draw(m).ellipse([0,0,s*4-1,s*4-1],fill=255)
    out=im.convert("RGBA"); out.putalpha(m.resize((s,s),Image.LANCZOS)); return out

icon=full_icon()
icon.convert("RGB").save(os.path.join(ROOT,"icon-1024.png"))
icon.resize((512,512),Image.LANCZOS).convert("RGB").save(os.path.join(ROOT,"play-icon-512.png"))
# In-app logo (feather only, transparent) used on the welcome screen
feather(512, scale=1.30, style="split").save(os.path.join(ROOT,"..","app","logo.png"))

# Adaptive icon foreground: Android crops to the middle 66 of 108 dp, so the feather is drawn smaller.
fg_feather=feather(1024, scale=0.82, style="split")
for name,k in {"mdpi":1,"hdpi":1.5,"xhdpi":2,"xxhdpi":3,"xxxhdpi":4}.items():
    d=os.path.join(ROOT,"res",f"mipmap-{name}"); os.makedirs(d,exist_ok=True)
    s=int(48*k); ic=icon.resize((s,s),Image.LANCZOS)
    rounded(ic,0.22).save(f"{d}/ic_launcher.png")
    circle(ic).save(f"{d}/ic_launcher_round.png")
    fs=int(108*k)
    fg=grad_bg(fs).convert("RGBA"); fg.alpha_composite(fg_feather.resize((fs,fs),Image.LANCZOS))
    fg.save(f"{d}/ic_launcher_foreground.png")

sizes={"drawable":(480,320),"drawable-port-mdpi":(320,480),"drawable-port-hdpi":(480,800),"drawable-port-xhdpi":(720,1280),"drawable-port-xxhdpi":(960,1600),"drawable-port-xxxhdpi":(1280,1920),
       "drawable-land-mdpi":(480,320),"drawable-land-hdpi":(800,480),"drawable-land-xhdpi":(1280,720),"drawable-land-xxhdpi":(1600,960),"drawable-land-xxxhdpi":(1920,1280)}
for dname,(w,h) in sizes.items():
    d=os.path.join(ROOT,"res",dname); os.makedirs(d,exist_ok=True)
    im=Image.new("RGB",(w,h),CREAM)
    s=int(min(w,h)*0.28); ic=rounded(icon.resize((s,s),Image.LANCZOS),0.28)
    im.paste(ic,((w-s)//2,(h-s)//2),ic); im.save(f"{d}/splash.png")
print("icons written")

# Status-bar icon: Android needs a plain white silhouette on a transparent background.
for name,px in {"mdpi":24,"hdpi":36,"xhdpi":48,"xxhdpi":72,"xxxhdpi":96}.items():
    d=os.path.join(ROOT,"res",f"drawable-{name}"); os.makedirs(d,exist_ok=True)
    feather(px, color=(255,255,255), spine=(255,255,255), tail=(255,255,255), scale=1.45, style="split", down=False).save(f"{d}/ic_stat_plume.png")
