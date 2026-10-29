# Draws the Plume icon (option B: clear feather) and writes every Android size.
# Usage: python3 tools/make_icons.py
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math
S=1024; K=3
PLUM=(0x4B,0x22,0x70); PLUM2=(0x8A,0x4C,0xC4); DEEP=(0x2A,0x0F,0x45); LIME=(0xD8,0xF2,0x64); INK=(0x2E,0x12,0x48); CREAM=(0xF7,0xF3,0xEE)

def lerp(a,b,t): return tuple(int(a[i]+(b[i]-a[i])*t) for i in range(len(a)))
def grad_bg(size, c1=PLUM2, c2=PLUM, c3=DEEP):
    small=128; im=Image.new("RGB",(small,small)); px=im.load()
    for y in range(small):
        for x in range(small):
            t=min(1,math.hypot(x-small,y)/(small*1.35))
            px[x,y]=lerp(c1,c2,t/0.55) if t<0.55 else lerp(c2,c3,(t-0.55)/0.45)
    return im.resize((size,size),Image.BICUBIC)

def bez(p0,p1,p2,p3,t):
    a=(1-t)**3;b=3*(1-t)**2*t;c=3*(1-t)*t**2;d=t**3
    return (a*p0[0]+b*p1[0]+c*p2[0]+d*p3[0], a*p0[1]+b*p1[1]+c*p2[1]+d*p3[1])
def bez_d(p0,p1,p2,p3,t):
    return (3*(1-t)**2*(p1[0]-p0[0])+6*(1-t)*t*(p2[0]-p1[0])+3*t**2*(p3[0]-p2[0]),
            3*(1-t)**2*(p1[1]-p0[1])+6*(1-t)*t*(p2[1]-p1[1])+3*t**2*(p3[1]-p2[1]))

def feather(size, color=LIME, quill=INK, scale=1.0, notches=True, quill_tail=LIME, cx=0.5, cy=0.5):
    """A proper feather: curved spine, asymmetric vane, two barb notches, visible quill tail."""
    W=size*K; im=Image.new("RGBA",(W,W),(0,0,0,0)); d=ImageDraw.Draw(im)
    u=W*scale
    # spine from base (lower-left) to tip (upper-right), gently curved
    ox,oy=W*cx,W*cy
    P=lambda x,y:(ox+x*u, oy+y*u)
    sp=[(-0.26,0.26),(-0.10,0.06),(0.06,-0.12),(0.27,-0.30)]
    left=[];right=[]
    N=120
    for i in range(N+1):
        t=i/N
        x,y=bez(*sp,t); dx,dy=bez_d(*sp,t); L=math.hypot(dx,dy); nx,ny=-dy/L,dx/L
        # vane only from t=0.18 (quill tail visible below)
        if t<0.16: continue
        tt=(t-0.16)/0.84
        wl=0.155*math.sin(math.pi*min(1,tt)**0.75)**0.9
        wr=0.115*math.sin(math.pi*min(1,tt)**0.70)**0.9
        if notches:
            # notches: pinch the vane at a few points like separated barbs
            for c,depth,side in [(0.62,0.55,'r'),(0.40,0.45,'l'),(0.78,0.5,'l')]:
                k=math.exp(-((tt-c)/0.028)**2)
                if side=='r': wr*= (1-depth*k)
                else: wl*=(1-depth*k)
        left.append(P(x+nx*wl, y+ny*wl)); right.append(P(x-nx*wr, y-ny*wr))
    d.polygon(left+right[::-1], fill=color+(255,))
    # spine
    pts=[P(*bez(*sp,i/60)) for i in range(61)]
    d.line(pts[int(60*0.16):int(60*0.97)], fill=quill+(255,), width=int(0.018*u), joint="curve")
    d.line(pts[:int(60*0.17)+1], fill=quill_tail+(255,), width=int(0.024*u), joint="curve")
    x,y=pts[0]; r=0.012*u; d.ellipse([x-r,y-r,x+r,y+r], fill=quill_tail+(255,))
    return im.resize((size,size),Image.LANCZOS)


import os
ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","brand")
def full_icon(size=S):
    im=grad_bg(size).convert("RGBA"); im.alpha_composite(feather(size, scale=1.25)); return im
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
feather(512, scale=1.25).save(os.path.join(ROOT,"..","app","logo.png"))

# Adaptive icon foreground: Android crops to the middle 66 of 108 dp, so the feather is drawn smaller.
fg_feather=feather(1024, scale=0.80)
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
    feather(px, color=(255,255,255), quill=(255,255,255), quill_tail=(255,255,255), scale=1.45).save(f"{d}/ic_stat_plume.png")
