# Builds the icon with the ship drawn in perspective (lines converge toward a point far left on the horizon).
H=300
def f(x): return (x+900)/1300
def P(x,y): return (x, H+(y-H)*f(x))
def poly(pts, fill, extra=''):
    d='M'+' L'.join('%.1f %.1f'%P(x,y) for x,y in pts)+' Z'
    return f'<path d="{d}" fill="{fill}" {extra}/>'
def band(y0,y1,x0,x1,fill,extra=''): return poly([(x0,y0),(x1,y0),(x1,y1),(x0,y1)],fill,extra)
out=[]
A=out.append
defs=open('defs.svg').read()
import sys
A(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{sys.argv[1]}">'+defs)
A('<rect x="-300" y="-300" width="1112" height="601" fill="url(#sky)"/><circle cx="462" cy="284" r="72" fill="url(#sun)"/><circle cx="462" cy="288" r="26" fill="#fff4cf"/>')
A('<rect x="-300" y="299" width="1112" height="600" fill="url(#sea)"/>')
A('<path d="M424 312 H500 M438 326 H492 M450 340 H484" stroke="#ffd59a" stroke-width="4" stroke-linecap="round" opacity=".75"/>')
# shadow/reflection on the water
A(poly([(-200,372),(400,372),(408,400),(-200,396)],'#062236','opacity=".5" filter="url(#soft)"'))
# funnel
A(poly([(232,70),(290,70),(298,140),(226,140)],'#163a57'))
A(poly([(232,70),(290,70),(292,86),(231,86)],'#f2b705'))
A(poly([(284,70),(290,70),(298,140),(292,140)],'#0a2338'))
# upper superstructure
A(poly([(50,128),(326,128),(338,138),(342,190),(44,190)],'url(#sup)'))
A(band(140,154,50,340,'url(#glass)'))
A(band(160,170,48,341,'url(#glass)'))
A(band(188,196,44,343,'#8aa1b0'))
# balcony decks
A(poly([(-200,190),(370,190),(384,200),(388,246),(-200,246)],'url(#sup)'))
A(band(202,214,-200,386,'url(#glass)'))
A(band(220,232,-200,387,'url(#glass)'))
A(band(244,250,-200,388,'#8aa1b0'))
# hull with rounded stern
stern=[(392,250),(408,254),(416,266),(418,286),(412,350),(406,366),(392,372)]
A(poly([(-200,250)]+stern+[(-200,372)],'url(#hull)'))
A(band(270,282,-200,414,'#26557a'))
for x in range(20,290,34):
    cx,cy=P(x,298); A(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{5*f(x):.1f}" fill="#26557a"/>')
A(poly([(-200,346),(413,346),(406,366),(392,372),(-200,372)],'#102c44'))
A(poly([(400,252),(412,258),(418,286),(412,350),(406,366),(394,372),(402,350),(408,286),(404,262)],'#9fb3c0','opacity=".7"'))
for x in (30,100,170,240):
    cx,cy=P(x+22,238); s=f(x+22)
    A(f'<rect x="{cx-22*s:.1f}" y="{cy-7*s:.1f}" width="{44*s:.1f}" height="{14*s:.1f}" rx="{7*s:.1f}" fill="#f28a1e"/>')
# lit shell door
A(poly([(300,304),(338,304),(338,346),(300,346)],'url(#door)'))
A('<path d="M-300 451 L812 425 L812 447 L-300 475 Z" fill="url(#quayTop)"/><path d="M-300 475 L812 447 L812 900 L-300 900 Z" fill="url(#quayFront)"/><path d="M-300 475 L812 447" stroke="#fff" stroke-width="2" opacity=".6"/>')
A('<rect x="78" y="422" width="22" height="30" rx="6" fill="#1b2f3d"/><ellipse cx="89" cy="422" rx="15" ry="6" fill="#2c4658"/>')
# gangway from the door down to the quay
dx,dy=P(300,346); ex,ey=P(338,346)
A(f'<path d="M{dx:.0f} {dy:.0f} L{dx:.0f} {dy+7:.0f} L432 455 L432 448 Z" fill="#a87b00"/>')
A(f'<path d="M{dx:.0f} {dy:.0f} L{ex:.0f} {ey:.0f} L482 442 L432 448 Z" fill="#f2b705"/>')
A(f'<path d="M{ex:.0f} {ey:.0f} L482 442 L482 450 L{ex:.0f} {ey+6:.0f} Z" fill="#d49e00"/>')
A('<g fill="none" stroke="#0f2a3a" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" opacity=".8"><path d="M368 392 L392 408 L410 386"/><path d="M402 418 L426 434 L444 412"/></g>')
A(f'<path d="M{dx:.0f} {dy-40:.0f} L432 408" stroke="#ffcf3a" stroke-width="7" stroke-linecap="round"/>')
A('<path d="M342 338 V376 M376 362 V402 M408 386 V428" stroke="#ffcf3a" stroke-width="5" stroke-linecap="round"/>')
A('</svg>')
open(sys.argv[2],'w').write('\n'.join(out))
