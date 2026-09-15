const fs=require('fs');
const src=fs.readFileSync(process.argv[2],'utf8');
const grab=(re)=>{const m=src.match(re);if(!m)throw new Error('no match '+re);return m[0];};
let OUTLETS_RAW, CLUSTER_REF;
eval(grab(/let\s+OUTLETS_RAW\s*=\s*\{[\s\S]*?\};/).replace(/^let\s+/,'OUTLETS_RAW = '));
eval(grab(/const\s+CLUSTER_REF\s*=\s*\{[\s\S]*?\};/).replace(/^const\s+/,'CLUSTER_REF = '));
const C=OUTLETS_RAW.cols, ic=C.indexOf('city'), ila=C.indexOf('lat'), ilo=C.indexOf('lon');
const cities=Object.keys(CLUSTER_REF).sort();
const PAD=0.02; const out=[];
for(const city of cities){
  let s=90,w=180,n=-90,e=-180;
  const add=(la,lo)=>{if(!isFinite(la)||!isFinite(lo))return;s=Math.min(s,la);n=Math.max(n,la);w=Math.min(w,lo);e=Math.max(e,lo);};
  CLUSTER_REF[city].points.forEach(p=>add(p[1],p[2]));
  OUTLETS_RAW.rows.forEach(r=>{if(r[ic]===city)add(r[ila],r[ilo]);});
  const bbox=[+(s-PAD).toFixed(4),+(w-PAD).toFixed(4),+(n+PAD).toFixed(4),+(e+PAD).toFixed(4)];
  const km2=(bbox[2]-bbox[0])*111*(bbox[3]-bbox[1])*111*Math.cos((s+n)/2*Math.PI/180);
  out.push({city,bbox,km2:Math.round(km2)});
}
const slug=c=>c.normalize('NFKD').replace(/[^\w\s-]/g,'').trim().toLowerCase().replace(/[\s_]+/g,'-').replace(/-+/g,'-');
out.forEach(o=>o.slug=slug(o.city));
const slugs=new Set(out.map(o=>o.slug)); if(slugs.size!==out.length)throw new Error('slug collision');
fs.writeFileSync(process.argv[3],JSON.stringify(out,null,1));
console.log('cities',out.length,'outlets',OUTLETS_RAW.rows.length);
out.sort((a,b)=>b.km2-a.km2); console.log('largest',out.slice(0,12).map(o=>o.city+':'+o.km2).join(', '));
console.log('smallest',out.slice(-5).map(o=>o.city+':'+o.km2).join(', '));
console.log('total km2',out.reduce((s,o)=>s+o.km2,0));
