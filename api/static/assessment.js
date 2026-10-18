/* The receipt and the extension consume the same v2 assessment; no UI-side scoring. */
(() => {
  "use strict";
  const $=(id)=>document.getElementById(id);
  const money=(v)=>v==null?"Unavailable":new Intl.NumberFormat("en-GB",{style:"currency",currency:"THB",maximumFractionDigits:0}).format(v);
  const date=(v)=>v?new Date(v+"T00:00:00").toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric"}):"Unknown";
  const q=new URLSearchParams(location.search);
  const kind=q.get("product")||"DDR5";
  const gb=Number(q.get("capacity_gb")||q.get("gb")||(kind==="DDR4"?16:kind==="NVME"||kind==="SATA"?1000:32));
  const synthetic=kind==="GPU"?"Graphics card "+(q.get("model")||"RX 9070 XT"):kind==="NVME"||kind==="SATA"?kind+" SSD "+gb+"GB":"RAM "+kind+" "+gb+"GB";
  $("today").textContent=new Date().toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric"});
  $("title-input").value=q.get("title")||synthetic;
  $("kind-input").value=kind;
  $("capacity-input").value=String(gb);
  $("model-input").value=q.get("model")||"";
  $("price-input").value=q.get("price")||"";
  $("confirmed-input").checked=q.get("confirmed")==="true";
  const from=q.get("from");
  try {
    const url=new URL(from);
    if(["http:","https:"].includes(url.protocol)){$("back").href=url.href;$("back").hidden=false;}
  }catch(_){}
  let assessment=null,range=365, requestId=0,controller;
  let params=new URLSearchParams({title:$("title-input").value});
  for(const k of ["price","product","model","capacity_gb","confirmed","ambiguous","title_source","price_source","variant_title","variant_label"])if(q.has(k))params.set(k,q.get(k));
  // Legacy navigation's product/gb is only a default, not a manual confirmation.
  if(!params.get("confirmed")){params.delete("product");params.delete("model");params.delete("capacity_gb");}
  function text(id,value){$(id).textContent=value==null?"Unavailable":String(value);}
  function list(id,rows){
    const root=$(id);root.replaceChildren();
    rows.forEach(([k,v])=>{const a=document.createElement("dt"),b=document.createElement("dd");a.textContent=k;b.textContent=v==null?"Unavailable":String(v);root.append(a,b);});
  }
  function fields(){
    const gpu=$("kind-input").value==="GPU";
    $("model-field").hidden=!gpu;$("capacity-field").hidden=gpu;
    $("model-input").required=gpu;$("capacity-input").required=!gpu;
  }
  $("kind-input").addEventListener("change",fields);fields();
  function number(v){return typeof v==="number"&&Number.isFinite(v);}
  function chart(id,lines,{season=false,month=null,unitIndex=false}={}){
    const root=$(id);root.replaceChildren();
    const valid=lines.flatMap(l=>l.points.filter(p=>number(p.y)));
    if(!valid.length){root.textContent="Not enough observed history for this chart.";return;}
    const W=Math.max(280,Math.round(root.clientWidth||600)),H=season?210:280;
    const m={l:64,r:14,t:15,b:38},minX=Math.min(...valid.map(p=>p.x)),maxX0=Math.max(...valid.map(p=>p.x)),maxX=maxX0===minX?minX+1:maxX0;
    const values=valid.flatMap(p=>[p.y,p.low,p.high]).filter(number);
    let minY=Math.min(...values),maxY=Math.max(...values);
    const pad=Math.max((maxY-minY)*.1,maxY*.02,season?1:1);
    minY=Math.max(0,minY-pad);maxY+=pad;
    const X=v=>m.l+(v-minX)/(maxX-minX)*(W-m.l-m.r);
    const Y=v=>H-m.b-(v-minY)/(maxY-minY)*(H-m.t-m.b);
    const NS="http://www.w3.org/2000/svg";
    const svg=document.createElementNS(NS,"svg");
    svg.setAttribute("viewBox","0 0 "+W+" "+H);svg.setAttribute("role","img");
    svg.setAttribute("aria-label",season?"Historical monthly seasonal price index":"Price evidence in THB, observed points and outlook");
    root.append(svg);
    const add=(tag,attrs,label)=>{
      const n=document.createElementNS(NS,tag);
      Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));
      if(label!=null)n.textContent=label;
      svg.append(n);return n;
    };
    add("title",{},season?"Seasonal context":"Price history and next 90 days");
    for(let i=0;i<=4;i++){
      const value=minY+(maxY-minY)*i/4;
      add("line",{x1:m.l,x2:W-m.r,y1:Y(value),y2:Y(value),stroke:"#b9b2a5","stroke-opacity":".35"});
      add("text",{x:m.l-8,y:Y(value)+4,"text-anchor":"end"},season||unitIndex?value.toFixed(0):"฿"+Math.round(value).toLocaleString("en-GB"));
    }
    const tickCount=W<430?3:5;
    const ticks=season?Array.from({length:12},(_,i)=>i+1):Array.from({length:tickCount},(_,i)=>minX+(maxX-minX)*i/(tickCount-1));
    const monthNames=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    ticks.forEach((t,i)=>{
      if(season&&W<430&&i%2)return;
      const label=season?monthNames[t-1]:new Date(t).toLocaleDateString("en-GB",{month:"short",year:"2-digit"});
      add("text",{x:X(t),y:H-12,"text-anchor":i===0?"start":i===ticks.length-1?"end":"middle"},label);
    });
    if(season&&month)add("line",{x1:X(month),x2:X(month),y1:m.t,y2:H-m.b,stroke:"#345c86","stroke-dasharray":"3 4"});
    const path=points=>points.map((p,i)=>(i?"L":"M")+X(p.x).toFixed(2)+","+Y(p.y).toFixed(2)).join(" ");
    for(const line of lines){
      const pts=line.points.filter(p=>number(p.y)).sort((a,b)=>a.x-b.x);
      if(!pts.length)continue;
      const band=pts.filter(p=>number(p.low)&&number(p.high));
      if(band.length>1){
        const edges=band.map(p=>({x:p.x,y:p.high})).concat([...band].reverse().map(p=>({x:p.x,y:p.low})));
        add("path",{d:path(edges)+"Z",fill:line.color,"fill-opacity":".12",stroke:"none"});
      }
      if(line.gaps){
        let start=null;
        pts.forEach((p,i)=>{
          if(p.gap&&start===null)start=p.x;
          if(start!==null&&(!p.gap||i===pts.length-1)){
            add("rect",{x:X(start),y:m.t,width:Math.max(1,X(p.x)-X(start)),height:H-m.t-m.b,fill:"#b9b2a5","fill-opacity":".18"});start=null;
          }
        });
      }
      if(!line.dotsOnly)add("path",{d:path(pts),fill:"none",stroke:line.color,"stroke-width":line.dashed?2:2.2,"stroke-dasharray":line.dashed?"5 5":"none"});
      for(const p of pts)if(p.observed||season)add("circle",{cx:X(p.x),cy:Y(p.y),r:season?3:2.4,fill:line.color});
    }
    const tooltip=document.createElement("div");tooltip.className="tooltip";tooltip.setAttribute("role","tooltip");root.append(tooltip);
    const guide=add("line",{x1:0,x2:0,y1:m.t,y2:H-m.b,stroke:"#625d54","stroke-dasharray":"2 4",opacity:0});
    const hit=add("rect",{x:m.l,y:m.t,width:W-m.l-m.r,height:H-m.t-m.b,fill:"transparent"});
    function details(evt){
      const rect=svg.getBoundingClientRect(),px=(evt.clientX-rect.left)*W/rect.width;
      const x=minX+(px-m.l)/(W-m.l-m.r)*(maxX-minX);
      guide.setAttribute("x1",X(x));guide.setAttribute("x2",X(x));guide.setAttribute("opacity",1);
      const rows=[];
      for(const line of lines){
        const pts=line.points.filter(p=>number(p.y));
        const nearest=pts.reduce((best,p)=>!best||Math.abs(p.x-x)<Math.abs(best.x-x)?p:best,null);
        if(!nearest)continue;
        const tolerance=season?.55:8*86400000;
        if(Math.abs(nearest.x-x)>tolerance)continue;
        rows.push(line.name+": "+(season||unitIndex?nearest.y.toFixed(1):money(nearest.y))+(nearest.filled?" (filled)":"")+(nearest.observed?" (observed)":""));
      }
      tooltip.textContent=(season?monthNames[Math.max(0,Math.min(11,Math.round(x)-1))]:date(new Date(x).toISOString().slice(0,10)))+" · "+rows.join(" · ");
      tooltip.style.display="block";tooltip.style.left=Math.max(0,Math.min(root.clientWidth-230,evt.clientX-rect.left))+"px";tooltip.style.top="16px";
    }
    hit.addEventListener("pointermove",details);hit.addEventListener("click",details);
    hit.addEventListener("pointerleave",()=>{tooltip.style.display="none";guide.setAttribute("opacity",0);});
  }
  function draw(){
    if(!assessment)return;
    const a=assessment,all=a.history||[],last=all.length?Date.parse(all[all.length-1].date):Date.now();
    const history=all.filter(p=>!range||Date.parse(p.date)>=last-range*86400000);
    const smooth=$("smooth").value==="ema";
    const lines=[{name:smooth?"EMA 30D":"Filled price",color:"#1f1d1a",gaps:true,points:history.map(p=>({x:Date.parse(p.date),y:smooth?p.ema_thb:p.value_thb,gap:p.long_gap,filled:p.filled}))},
      {name:"Observed",color:"#216342",dotsOnly:true,points:history.filter(p=>p.observed_thb!=null).map(p=>({x:Date.parse(p.date),y:p.observed_thb,observed:true}))}];
    if(a.outlook.points.length)lines.push({name:a.outlook.status==="scenario"?"Scenario":"Forecast",color:"#345c86",dashed:true,points:a.outlook.points.map(p=>({x:Date.parse(p.date),y:p.value_thb,low:p.low_thb,high:p.high_thb}))});
    chart("price-chart",lines);
    chart("season-chart",[{name:"Seasonal index",color:"#345c86",points:a.seasonality.profile.map(p=>({x:p.month,y:p.index}))}],{season:true,month:a.seasonality.current_month});
    const channels=Object.entries(a.channels||{}).map(([name,rows],i)=>({name,color:i?"#345c86":"#216342",points:rows.map(p=>({x:Date.parse(p.date),y:p.value_thb,observed:true}))}));
    chart("channels-chart",channels);
    if(a.category_context)chart("category-chart",[{name:"Market index",color:"#345c86",points:a.category_context.points.map(p=>({x:Date.parse(p.date),y:p.value}))}],{unitIndex:true});
  }
  function render(a){
    assessment=a;
    const p=a.product,e=a.evidence,r=a.price_assessment,o=a.outlook,s=a.seasonality;
    text("product-name",p.model||((p.generation||p.interface)+" · "+p.capacity_gb+" GB"));
    text("selection-note",a.product_match.selection_note);$("selection-note").hidden=!a.product_match.selection_note;
    text("listing-title",$("title-input").value);text("verdict",r.label);$("verdict").className="word "+r.status;
    list("prices",[["Your price",money(r.listing_thb)],["Reference midpoint",money(r.reference_thb)],["Reference range",r.low_thb!=null?money(r.low_thb)+"–"+money(r.high_thb):"Not enough evidence"],["Difference",r.diff_pct==null?"Unavailable":(r.diff_pct>0?"+":"")+r.diff_pct.toFixed(1)+"%"],["Comparison scope",r.scope]]);
    text("price-reason",r.reason);text("timing-label",s.label);text("timing-short",s.years+" historical years · "+(s.group||"Historical context"));
    text("outlook-kind","Next 90 days · "+(o.status==="validated_forecast"?"Forecast":o.status==="scenario"?"Scenario":"Unavailable"));
    text("outlook-label",o.label);text("outlook-short",o.reason);
    text("season-reason",s.reason);text("why-price",r.reason);
    text("why-timing",s.reason+" "+(s.status==="supported"?"The current month is compared with the lowest and highest thirds of the supported profile.":"Historical curves alone do not establish a reliable buying season."));
    text("why-outlook",o.reason+" "+(o.fx_assumption||""));
    text("forecast-reason",o.reason+". "+(o.interval_kind||"")+" · "+(o.fx_assumption||"")+" "+(o.price_basis||""));
    text("forecast-legend",o.status==="scenario"?"Illustrative scenario":o.status==="validated_forecast"?"Forecast":"Outlook unavailable");
    list("evidence",[["Last observed",date(e.last_observed_date)],["Observation age",e.age_days==null?"Unknown":e.age_days+" days"],["Confidence",e.confidence],["Observed days",e.observed_days],["Filled history",e.filled_share_pct==null?"Unavailable":e.filled_share_pct+"%"],["Sources",(e.sources||[]).join(", ")||"None"],["FX rate",e.fx_rate==null?"Unavailable":"1 USD = ฿"+e.fx_rate.toFixed(3)],["FX observed",date(e.fx_date)],["Title origin",a.product_match.title_source],["Price origin",a.product_match.price_source]]);
    $("limitations").replaceChildren(...(e.limitations||[]).map(t=>{const li=document.createElement("li");li.textContent=t;return li;}));
    const validation=e.reference_validation||{};
    text("reference-validation",validation.n==null?"No matched reference validation.":validation.n+" observed targets · "+validation.method+". "+validation.interval_kind);
    $("validation-table").replaceChildren(...(o.validation||[]).map(r=>{
      const tr=document.createElement("tr");
      [r.horizon_days+"D",r.n,r.mae==null?"—":r.mae.toFixed(3),r.carry_mae==null?"—":r.carry_mae.toFixed(3),r.passed?"Passed":"Not validated"].forEach(v=>{const td=document.createElement("td");td.textContent=v;tr.append(td);});return tr;
    }));
    text("season-validation",(s.validation||[]).length?s.validation.map(r=>r.year+": "+r.months+" months, correlation "+(r.correlation==null?"unavailable":r.correlation.toFixed(2))).join("; "):"Not enough qualifying years for leave-one-year-out validation.");
    $("results").hidden=false;$("details").hidden=false;
    $("category-context").hidden=!a.category_context;
    $("stale-warning").hidden=!(e.stale||a.dataset_warning||a.product_match.needs_confirmation);
    text("stale-warning",a.product_match.needs_confirmation?"Provisional comparison assumes the displayed product and capacity. Check or adjust the option below.":a.dataset_warning||(e.stale?"Older reference: price comparison remains available, but is not a current market valuation. Outlook is withheld.":""));
    if(a.product_match.needs_confirmation)$("edit").open=true;
    $("kind-input").value=p.category==="GPU"?"GPU":p.generation||p.interface;
    if(p.model)$("model-input").value=p.model;
    if(p.capacity_gb)$("capacity-input").value=p.capacity_gb;
    fields();
    text("updated","Dataset "+a.dataset_version+" · Snapshot "+date(a.dataset_asof)+" · Assessment "+date(a.assessment_date));
    draw();
  }
  async function load(){
    const mine=++requestId;
    if(controller)controller.abort();controller=new AbortController();
    const activeController=controller;
    $("loading").hidden=false;$("error").hidden=true;$("check-btn").disabled=true;
    $("results").hidden=true;$("details").hidden=true;
    const timeout=setTimeout(()=>activeController.abort(),12000);
    try{
      const response=await fetch("/api/v2/assessment?"+params,{signal:activeController.signal});
      const a=await response.json();
      if(!response.ok)throw new Error(typeof a.detail==="string"?a.detail:"Unable to load price evidence.");
      if(mine!==requestId)return;
      if(!a.covered)throw new Error(a.reason+" Confirm a supported product below.");
      render(a);
    }catch(err){
      if(mine!==requestId)return;
      text("error",err.name==="AbortError"?"The request timed out. Refresh evidence to retry.":err.message);
      $("error").hidden=false;$("edit").open=true;assessment=null;
    }finally{clearTimeout(timeout);if(mine===requestId){$("loading").hidden=true;$("check-btn").disabled=false;}}
  }
  $("check-form").addEventListener("submit",event=>{
    event.preventDefault();
    params=new URLSearchParams({title:$("title-input").value,confirmed:"true",product:$("kind-input").value,title_source:"manual",price_source:"manual"});
    if($("price-input").value)params.set("price",$("price-input").value);
    if($("kind-input").value==="GPU")params.set("model",$("model-input").value);else params.set("capacity_gb",$("capacity-input").value);
    const url=new URL(location.href);url.search=params.toString();if(from)url.searchParams.set("from",from);
    history.replaceState(null,"",url);load();
  });
  $("retry").addEventListener("click",load);
  document.querySelectorAll("[data-range]").forEach(button=>button.addEventListener("click",()=>{
    range=Number(button.dataset.range);
    document.querySelectorAll("[data-range]").forEach(b=>b.setAttribute("aria-pressed",String(b===button)));draw();
  }));
  $("smooth").addEventListener("change",draw);
  document.querySelector("#details details").addEventListener("toggle",draw);
  let resizeTimer;window.addEventListener("resize",()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(draw,100);});
  load();
})();
