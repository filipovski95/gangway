const {chromium}=require(require('child_process').execSync('npm root -g').toString().trim()+'/playwright');
const fs=require('fs'),path=require('path');const out=process.argv[2];const r=f=>fs.readFileSync(f,'utf8');
const L=r('legacy.svg'),F=r('fg.svg'),P=r('play.svg');
const jobs=[];const dens={mdpi:1,hdpi:1.5,xhdpi:2,xxhdpi:3,xxxhdpi:4};
for(const [d,f] of Object.entries(dens)){
  jobs.push([`res/mipmap-${d}/ic_launcher.png`,48*f,'',L]);
  jobs.push([`res/mipmap-${d}/ic_launcher_round.png`,48*f,'border-radius:50%;overflow:hidden;',L]);
  jobs.push([`res/mipmap-${d}/ic_launcher_foreground.png`,108*f,'',F]);
}
jobs.push(['play-icon-512.png',512,'',P]);
(async()=>{const b=await chromium.launch();const p=await b.newPage();
for(const [rel,size,clip,svg] of jobs){await p.setViewportSize({width:size,height:size});
await p.setContent(`<style>html,body{margin:0;background:transparent}div{width:${size}px;height:${size}px;${clip}}svg{width:100%;height:100%;display:block}</style><div>${svg}</div>`);
const o=path.join(out,rel);fs.mkdirSync(path.dirname(o),{recursive:true});await p.screenshot({path:o,omitBackground:true});}
await b.close();})();
