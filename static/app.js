"use strict";
const $ = id => document.getElementById(id);
const state = {demo:false, holdings:[], picked:[], result:null, file:null, info:null, busy:false, lookupIndex:null, importNote:"", selected:null};
const money = (n, currency=state.result?.currency || $("currency").value) => new Intl.NumberFormat("en-GB", {style:"currency",currency,maximumFractionDigits:0}).format(n);
const node = (tag, text, className) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;};
// Remember dismissed notices only for this session; new notices and errors still appear.
const dismissedNotices=new Set();
function message(text="", error=false){$("message-text").textContent=text;$("message").hidden=!text||(!error&&dismissedNotices.has(text));$("message").className=error?"error":"";}
$("dismiss-message").addEventListener("click",()=>{if(!$("message").classList.contains("error"))dismissedNotices.add($("message-text").textContent);$("message").hidden=true;});
function dirty(){ if(state.running&&typeof cancelBackground==="function")cancelBackground(); if(!state.result)return; $("results").classList.add("outdated");$("download").disabled=true;$("chart-note").textContent="Settings changed — run the simulation to update this graph."; }
function busy(on, label="Working…"){
  state.busy=on;
  document.querySelectorAll("button,input,select").forEach(el=>{el.disabled=on;});
  document.querySelectorAll('label[for="upload"]').forEach(el=>el.setAttribute("aria-disabled",String(on)));
  $("dismiss-message").disabled=false;
  $("download").disabled=on||!state.result||$("results").classList.contains("outdated");
  $("results").setAttribute("aria-busy",String(on));
  $("loading-state").hidden=!on;$("loading-text").textContent=label;
  $("run").disabled=on||(!state.demo&&!state.holdings.length);
  $("refresh").disabled=on||(!state.demo&&!state.holdings.length);
  if($("simulate-picked"))$("simulate-picked").disabled=on||!state.picked.length;
  if(!on&&$("picker-panel")&&!$("picker-panel").hidden)renderPicker();
  $("run").textContent=on?label:"Run simulation";
  if(!on&&typeof syncExperimentControls==="function")syncExperimentControls();
}
async function api(url, options={}){
  const response=await fetch(url,{...options,signal:AbortSignal.timeout(180000)});
  const data=await response.json().catch(()=>({error:"The server returned an invalid response. Please retry."}));
  if(!response.ok)throw new Error(data.error||"Request failed.");return data;
}
function settings(refresh=false){return {holdings:state.holdings.map(h=>({symbol:h.symbol,quantity:Number(h.quantity),declared_kind:h.declared_kind})), demo:state.demo, currency:$("currency").value,selection:document.querySelector('[name="selection"]:checked').value,years:Number($("years").value),paths:Number($("paths").value),seed:Number($("seed").value),allow_stale:$("allow-stale").checked,refresh,...experimentSettings()};}
async function run(refresh=false){return runBackground(refresh);}

function stored(key, fallback){try{return JSON.parse(localStorage.getItem(key))??fallback;}catch{return fallback;}}
function save(key,value){try{localStorage.setItem(key,JSON.stringify(value));}catch{}}
function colors(){const css=getComputedStyle(document.documentElement);return Object.fromEntries(["ink","muted","line","paper","surface","accent","path","highlight","band90","band50"].map(k=>[k,css.getPropertyValue(`--${k}`).trim()]));}
function applyTheme(theme){document.documentElement.dataset.theme=theme;const dark=theme==="dark";$("theme-toggle").setAttribute("aria-pressed",String(dark));$("theme-toggle").textContent=dark?"Light mode":"Dark mode";}
applyTheme(stored("portfolio-theme",matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"));
function chartLayout(){const c=colors();return {paper_bgcolor:c.paper,plot_bgcolor:c.paper,font:{family:'-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',size:11,color:c.muted},margin:{l:62,r:16,t:18,b:42},showlegend:false,hovermode:"closest",clickmode:"event",hoverdistance:15,hoverlabel:{bgcolor:c.surface,font:{size:12,color:c.ink}},xaxis:{showgrid:false,zeroline:false,fixedrange:true},yaxis:{gridcolor:c.line,zeroline:false,fixedrange:true}};}
function highlightPath(index){
  const previous=state.selected;
  state.selected=previous===index?null:index;
  const graph=$("chart"),c=colors(),comparison=state.result.comparisons?.length>1;
  // No redraw on initial render; a click updates only affected paths in one batch.
  const indices=comparison&&previous!==state.selected
    ?graph.data.map((_,i)=>i).filter(i=>graph.data[i].meta?.baseWidth!==undefined)
    :[...new Set([previous,state.selected])].filter(i=>i!==null&&graph.data[i]?.meta?.baseWidth!==undefined);
  if(indices.length)Plotly.restyle(graph,{
    "line.width":indices.map(i=>state.selected===i?3.5:graph.data[i].meta.baseWidth),
    "line.color":indices.map(i=>!comparison&&state.selected===i?c.highlight:graph.data[i].meta.baseColor),
    opacity:indices.map(i=>!comparison||state.selected===null||state.selected===i?1:.25)
  },indices);
  document.querySelectorAll('[data-model-trace]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.modelTrace)===state.selected)));
  const trace=state.selected===null?null:graph.data[state.selected];
  const hint=state.result.comparisons?.length>1?"Median outcomes only. Click a model name or line to focus it; click again to clear.":`${state.result.sample_paths.length} sample paths shown. Click a path to highlight it; click it again to clear.`;
  $("clear-path").hidden=!trace;
  $("selection-note").textContent=trace?`${trace.name} | final value ${money(trace.y.at(-1))} | click again to clear`:hint;
}
function rememberListing(holding){if(!holding.identifier||!holding.symbol)return;const choices=stored("portfolio-listings",{});choices[holding.identifier]=holding.symbol;save("portfolio-listings",choices);}
async function resolveHoldings(){
  const choices=stored("portfolio-listings",{});
  state.holdings.forEach(h=>{if(!h.symbol&&typeof choices[h.identifier]==="string")h.symbol=choices[h.identifier];});
  const missing=state.holdings.filter(h=>!h.symbol);
  for(let i=0;i<missing.length;i+=4){
    message(`Choosing exchange listings… ${Math.min(i+4,missing.length)} of ${missing.length}`);
    const data=await api("/api/resolve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({identifiers:missing.slice(i,i+4).map(h=>h.identifier),currency:$("currency").value})});
    missing.slice(i,i+4).forEach(h=>{const listing=data.listings[h.identifier];if(listing){h.symbol=listing.symbol;h.listing_note=`Auto-selected | ${listing.exchange} | ${listing.currency}`;rememberListing(h);}});
  }
}
const plotConfig={responsive:true,displayModeBar:false,staticPlot:false};
// Navigation changes only the view, never the simulated values.
const chartView={mode:"pan",result:null,revision:0};
function setChartMode(mode){
  chartView.mode=mode;
  $("chart-pan").setAttribute("aria-pressed",String(mode==="pan"));
  $("chart-zoom").setAttribute("aria-pressed",String(mode==="zoom"));
  $("chart-navigation-help").textContent=mode==="pan"?"Scroll to zoom | Drag to move":"Scroll to zoom | Drag an area to zoom";
  if(state.result)Plotly.relayout("chart",{dragmode:mode});
}
$("chart-pan").addEventListener("click",()=>setChartMode("pan"));
$("chart-zoom").addEventListener("click",()=>setChartMode("zoom"));
$("chart-reset").addEventListener("click",()=>{
  if(state.result)Plotly.relayout("chart",{"xaxis.range":[0,state.result.years],"xaxis.autorange":false,"yaxis.autorange":true});
});
function renderResult(r){
  // Keep a zoomed view when changing theme; new results start at the full range.
  if(chartView.result!==r){chartView.result=r;chartView.revision++;}
  $("empty-chart").hidden=true;$("chart").hidden=false;
  ["metrics","chart-legend","chart-footer","chart-navigation","selection-row","distribution","holdings-panel"].forEach(id=>$(id).hidden=false);
  const percent=(r.median/r.initial-1)*100;
  $("median-return").textContent=`(${percent>=0?"+":""}${percent.toFixed(1)}%)`;
  $("initial").textContent=money(r.initial);$("median").textContent=money(r.median);$("range").textContent=`${money(r.p05)} – ${money(r.p95)}`;$("loss").textContent=`${(r.loss_probability*100).toFixed(1)}%`;
  const title={All:"all holdings",Stock:"stocks only",ETF:"ETFs only"}[r.selection];
  if(r.demo){$("data-label").textContent=`Example portfolio | synthetic data, not market prices | ${title}`;}
  else{
    const dates=r.holdings.map(h=>h.date).sort();
    const range=dates[0]===dates.at(-1)?dates[0]:`${dates[0]} to ${dates.at(-1)}`;
    const old=r.warnings.some(w=>w.includes("saved or older"));
    $("data-label").textContent=`${old?"Saved/older":"Latest available"} closing prices | ${range} | ${r.holdings.length} holding${r.holdings.length===1?"":"s"}${r.excluded_holdings?.length?` | ${r.excluded_holdings.length} automatically excluded`:""} | ${title}`;
  }
  $("history-note").textContent=r.demo?"Example mode uses 60 months of synthetic returns and an illustrative EUR/USD conversion (1 EUR = 1.10 USD).":`Calibration: ${r.months} shared monthly returns, ${r.history_start} through ${r.history_end}. Sources: Yahoo Finance adjusted closes; daily FX from Frankfurter or Yahoo Finance. At least 24 shared monthly returns are required.`;
  $("chart-note").textContent=`${r.paths.toLocaleString()} paths | ${r.years} years | monthly steps | seed ${r.seed}${r.demo?" | synthetic example":""}`;
  const x=r.time,c=colors(),layoutBase=chartLayout();
  const traces=[
    {x,y:r.bands["5"],type:"scatter",mode:"lines",line:{width:0},hoverinfo:"skip"},
    {x,y:r.bands["95"],type:"scatter",mode:"lines",line:{width:0},fill:"tonexty",fillcolor:c.band90,hoverinfo:"skip"},
    {x,y:r.bands["25"],type:"scatter",mode:"lines",line:{width:0},hoverinfo:"skip"},
    {x,y:r.bands["75"],type:"scatter",mode:"lines",line:{width:0},fill:"tonexty",fillcolor:c.band50,hoverinfo:"skip"},
    ...r.sample_paths.map((y,i)=>({x,y,name:`Path ${i+1}`,type:"scatter",mode:"lines+markers",marker:{size:x.map((_,j)=>j===x.length-1?5:0),color:c.path},line:{color:c.path,width:1},meta:{baseWidth:1,baseColor:c.path},hovertemplate:`Year %{x:.1f}<br>%{y:,.0f} ${r.currency}<extra>Path ${i+1}</extra>`})),
    {x,y:r.bands["5"],name:"5th percentile",type:"scatter",mode:"lines",meta:{baseWidth:.7,baseColor:c.accent},line:{color:c.accent,width:.7,dash:"dot"},hovertemplate:`%{y:,.0f} ${r.currency}<extra>5th percentile</extra>`},
    {x,y:r.bands["95"],name:"95th percentile",type:"scatter",mode:"lines",meta:{baseWidth:.7,baseColor:c.accent},line:{color:c.accent,width:.7,dash:"dot"},hovertemplate:`%{y:,.0f} ${r.currency}<extra>95th percentile</extra>`},
    {x,y:r.bands["50"],name:"Median",type:"scatter",mode:"lines",meta:{baseWidth:2.4,baseColor:c.accent},line:{color:c.accent,width:2.4},hovertemplate:`%{y:,.0f} ${r.currency}<extra>Median</extra>`}
  ];
  decorateResults(traces,r);
  const displayTraces=compactChartMarkers(traces,r.currency);
  const rendered=Plotly.react("chart",displayTraces,{...layoutBase,dragmode:chartView.mode,uirevision:chartView.revision,hovermode:r.comparisons?.length>1?"x unified":"closest",xaxis:{...layoutBase.xaxis,fixedrange:false,title:{text:r.backtest?"Years from backtest start":"Years from now",standoff:14},range:[0,r.years],nticks:6},yaxis:{...layoutBase.yaxis,fixedrange:false,title:{text:r.currency,standoff:10},rangemode:"tozero",tickformat:"~s"},shapes:[{type:"line",xref:"paper",x0:0,x1:1,y0:r.initial,y1:r.initial,line:{color:c.muted,width:1,dash:"dot"}}]},{...plotConfig,scrollZoom:true,doubleClick:"reset"}).then(()=>{
    const chart=$("chart");chart.removeAllListeners("plotly_click");chart.on("plotly_click",event=>{const point=event.points?.[0];if(!point)return;const index=chart.data[point.curveNumber]?.meta?.markerTargets?point.customdata[0]:point.curveNumber;if(chart.data[index]?.meta?.baseWidth!==undefined)highlightPath(index);});
    const selected=state.selected;state.selected=null;highlightPath(selected);
  });
  renderHistogram();
  return Promise.all([rendered,renderAllocation(r)]);
}
function renderHistogram(){
  if(!state.result||!$("distribution").open)return;
  const r=state.result,h=r.histogram,layoutBase=chartLayout(),c=colors();
  Plotly.react("histogram",[{x:h.centers,y:h.counts,width:h.widths,type:"bar",marker:{color:c.accent,line:{width:1,color:c.paper}},hovertemplate:`%{x:,.0f} ${r.currency}<br>%{y} simulations<extra></extra>`}],{...layoutBase,hovermode:"closest",xaxis:{...layoutBase.xaxis,title:{text:`Final portfolio value (${r.currency})`},tickformat:"~s"},yaxis:{...layoutBase.yaxis,title:{text:"Simulations"}}},plotConfig);
}
// Slice sizes use the same currency-converted starting values as the simulation.
function renderAllocation(r){
  const holdings=r.holdings.filter(h=>Number(h.value)>0).slice().sort((a,b)=>b.value-a.value);
  const total=holdings.reduce((sum,h)=>sum+Number(h.value),0),c=colors();
  $("allocation-panel").hidden=!holdings.length;
  if(!holdings.length)return;
  const grouped=holdings.length>8;
  const slices=grouped?[...holdings.slice(0,7),{name:`Other (${holdings.length-7} holdings)`,value:holdings.slice(7).reduce((sum,h)=>sum+Number(h.value),0)}]:holdings;
  const palette=[c.accent,c.highlight,c.ink,c.muted,'#587eb8','#a28ab8','#668f91','#888888'];
  $("allocation-note").textContent=`Starting allocation by value (${r.currency}) | ${r.demo?'synthetic example':'latest available closing prices'}${r.excluded_holdings?.length?' | Excluded holdings are not included.':''}${grouped?' | Smaller positions are grouped in the chart; every holding is listed.':''}`;
  const table=simpleTable(['Holding',`Value (${r.currency})`,'Weight'],holdings.map(h=>[`${h.name||h.symbol}${h.symbol&&h.name?` (${h.symbol})`:''}`,money(h.value,r.currency),`${(h.value/total*100).toFixed(1)}%`]));
  [...table.tBodies[0].rows].forEach((row,i)=>{const swatch=node('i',undefined,'allocation-swatch');swatch.style.background=palette[grouped&&i>=7?7:i];row.cells[0].prepend(swatch);});
  $("allocation-table").replaceChildren(table);
  return Plotly.react('allocation-chart',[{type:'pie',labels:slices.map(h=>h.symbol||h.name),values:slices.map(h=>h.value),hole:.58,sort:false,direction:'clockwise',textinfo:'percent',textposition:'inside',textfont:{size:12,color:c.paper},marker:{colors:palette,line:{color:c.paper,width:3}},hovertemplate:`%{label}<br>%{value:,.0f} ${r.currency}<br>%{percent}<extra></extra>`}],{...chartLayout(),margin:{l:12,r:12,t:16,b:16},annotations:[{text:'Starting value',x:.5,y:.56,xref:'paper',yref:'paper',showarrow:false,font:{size:12,color:c.muted}},{text:money(total,r.currency),x:.5,y:.45,xref:'paper',yref:'paper',showarrow:false,font:{size:22,color:c.ink}}]},plotConfig);
}
function simpleTable(headers, rows){const table=node("table"),head=node("thead"),tr=node("tr");headers.forEach(h=>tr.append(node("th",h)));head.append(tr);table.append(head);const body=node("tbody");rows.forEach(row=>{const line=node("tr");row.forEach(v=>line.append(node("td",String(v??""))));body.append(line);});table.append(body);return table;}
function renderHoldings(){
  $("holdings-panel").hidden=!state.demo&&!state.holdings.length;
  const box=$("holdings");box.replaceChildren();
  const details=new Map((state.result?.holdings||[]).map(h=>[h.symbol,h]));
  const excluded=new Map((state.result?.excluded_holdings||[]).map(h=>[h.symbol,h]));
  $("holdings-title").textContent=state.demo?"Example holdings":`Holdings (${state.holdings.length})`;
  $("holdings-help").textContent=state.demo?"The example uses invented securities and prices.":"Listings are selected automatically and remembered. You can change any ticker or use Find listing to override it. Currency and stock/ETF classification are verified from market data; changes require a new simulation. " + state.importNote;
  if(state.demo){box.append(simpleTable(["Holding","Type","Value"],(state.result?.holdings||[]).map(h=>[h.name,h.kind,money(h.value)])));return;}
  const table=simpleTable(["Identifier / listing","Ticker","Shares","CSV type","Latest closing price / source",""],[]),tbody=table.querySelector("tbody");
  state.holdings.forEach((h,i)=>{
    const row=node("tr"),ident=node("td",h.identifier);ident.append(node("small",h.name));row.append(ident);
    const tickerCell=node("td"),ticker=node("input");ticker.value=h.symbol;ticker.placeholder="e.g. VWCE.DE";ticker.setAttribute("aria-label",`Ticker for ${h.identifier}`);ticker.maxLength=25;ticker.addEventListener("change",()=>{h.symbol=ticker.value.trim().toUpperCase();ticker.value=h.symbol;rememberListing(h);dirty();});tickerCell.append(ticker);if(h.listing_note)tickerCell.append(node("small",h.listing_note));
    const search=node("button","Find listing","quiet");search.addEventListener("click",()=>openLookup(i));tickerCell.append(search);row.append(tickerCell);
    const qtyCell=node("td"),qty=node("input");qty.type="number";qty.min="0.000000001";qty.step="any";qty.value=h.quantity;qty.setAttribute("aria-label",`Shares for ${h.identifier}`);qty.addEventListener("change",()=>{h.quantity=Number(qty.value);dirty();});qtyCell.append(qty);row.append(qtyCell);
    const kindCell=node("td"),kind=node("select");["Auto","Stock","ETF"].forEach(v=>{const o=node("option",v);o.value=v;kind.append(o);});kind.value=h.declared_kind;kind.setAttribute("aria-label",`Type for ${h.identifier}`);kind.addEventListener("change",()=>{h.declared_kind=kind.value;dirty();});kindCell.append(kind);row.append(kindCell);
    const d=details.get(h.symbol),price=node("td",d?`${d.close.toLocaleString("en-GB",{maximumFractionDigits:4})} ${d.currency}`:"Run to fetch");
    if(excluded.has(h.symbol)){price.textContent="Automatically excluded from simulation";price.append(node("small",excluded.get(h.symbol).reason));}
    if(d){price.append(node("small",`${d.date} | ${d.kind} | ${d.exchange}`),node("small",`${d.stale?"SAVED/OLDER | ":""}${d.source}${d.cached?" | cached":""}`));if(d.fx_date)price.append(node("small",`FX ${d.fx_rate.toFixed(5)} | ${d.fx_date} | ${d.fx_source}`));}
    row.append(price);const removeCell=node("td"),remove=node("button","Remove","quiet");remove.setAttribute("aria-label",`Remove ${h.identifier}`);remove.addEventListener("click",()=>{state.holdings.splice(i,1);dirty();renderHoldings();});removeCell.append(remove);row.append(removeCell);tbody.append(row);
  });box.append(table);
}
async function inspectFile(){
  cancelBackground();
  const file=$("upload").files[0];if(!file)return;
  if(file.size>2*1024*1024){message("Choose a CSV smaller than 2 MB.",true);return;}
  busy(true,"Reading CSV…");message();
  try{
    const form=new FormData();form.append("file",file);state.info=await api("/api/inspect",{method:"POST",body:form});state.file=file;
    const scalable=state.info.format==="scalable_transactions";
    $("import-title").textContent=scalable?"Scalable Capital transactions detected":"Match your holdings columns";
    $("import-help").textContent=scalable?"Buys, savings plans and reinvestments add shares; sells subtract them. Pending/cancelled trades and cash movements are ignored. Use the full history and review the resulting quantities.":"Map your current holdings columns below.";
    $("decimal").parentElement.hidden=scalable;
    $("import-confirm").textContent=scalable?"Calculate holdings":"Import holdings";
    const mappings=$("mappings");mappings.hidden=scalable;mappings.replaceChildren();
    for(const [field,label] of Object.entries({identifier:"Ticker or ISIN *",quantity:"Shares / quantity *",name:"Name (optional)",kind:"Asset type (optional)"})){
      const l=node("label",label),select=node("select");select.dataset.field=field;select.append(node("option","— Not mapped —"));select.firstChild.value="";
      state.info.headers.forEach(h=>{const o=node("option",h);o.value=h;select.append(o);});select.value=state.info.mapping[field];l.append(select);mappings.append(l);
    }
    $("csv-preview").replaceChildren(simpleTable(state.info.headers,state.info.preview.map(row=>state.info.headers.map(h=>row[h]))));
    $("mapping-panel").hidden=false;$("mapping-panel").scrollIntoView({behavior:"smooth",block:"nearest"});
  }catch(e){message(e.message,true);}finally{busy(false);}
}
async function importFile(){
  busy(true,"Preparing holdings…");message();
  try{
    const mapping=Object.fromEntries([...document.querySelectorAll("#mappings select")].map(el=>[el.dataset.field,el.value]));
    const form=new FormData();form.append("file",state.file);form.append("mapping",JSON.stringify(mapping));form.append("decimal",$("decimal").value);
    const result=await api("/api/import",{method:"POST",body:form});state.holdings=result.holdings;state.importNote=(result.warnings||[]).join(" ");state.demo=false;resetResults();$("mapping-panel").hidden=true;if($("picker-panel"))$("picker-panel").hidden=true;
    try{await resolveHoldings();}catch(e){state.importNote+=" Automatic listing lookup could not finish. Retry Run simulation to try again.";}
    $("data-label").textContent="Holdings imported | run to fetch latest available closing prices";dirty();renderHoldings();$("holdings-panel").open=true;
    message(`${state.holdings.length} holdings imported.${result.skipped?` ${result.skipped} non-holding, inactive or zero-quantity rows excluded.`:""}${state.holdings.some(h=>!h.symbol)?" Some listings could not be found automatically; retry or use Find listing.":" Review the quantities, then run."} ${state.importNote}`);
    $("holdings-panel").scrollIntoView({behavior:"smooth",block:"nearest"});
  }catch(e){message(e.message,true);}finally{busy(false);}
}
function openLookup(i){state.lookupIndex=i;$("lookup").hidden=false;$("lookup-query").value=state.holdings[i].identifier;$("lookup-results").replaceChildren();$("lookup-query").focus();lookup();}
async function lookup(){
  const index=state.lookupIndex,holding=state.holdings[index];if(!holding)return;
  $("lookup-search").disabled=true;$("lookup-results").textContent="Searching listings…";
  try{
    const data=await api(`/api/search?q=${encodeURIComponent($("lookup-query").value)}`);if(state.holdings[index]!==holding)return;
    $("lookup-results").replaceChildren();
    if(!data.results.length)$("lookup-results").textContent="No verified listing found. Enter the exchange ticker directly, or search by the security name.";
    data.results.forEach(result=>{const b=node("button",`${result.symbol} | ${result.name} | ${result.exchange} | ${result.kind}`);b.addEventListener("click",()=>{holding.symbol=result.symbol;rememberListing(holding);$("lookup").hidden=true;dirty();renderHoldings();});$("lookup-results").append(b);});
  }catch(e){$("lookup-results").textContent=e.message;}finally{$("lookup-search").disabled=false;}
}
$("theme-toggle").addEventListener("click",()=>{const theme=document.documentElement.dataset.theme==="dark"?"light":"dark";applyTheme(theme);save("portfolio-theme",theme);if(state.result){const wasDirty=$("results").classList.contains("outdated");renderResult(state.result);if(wasDirty)dirty();}});
$("clear-path").addEventListener("click",()=>highlightPath(state.selected));
$("run").addEventListener("click",()=>run());$("refresh").addEventListener("click",()=>run(true));
$("example").addEventListener("click",()=>{state.demo=true;state.holdings=[];state.importNote="";$("mapping-panel").hidden=true;$("lookup").hidden=true;if($("picker-panel"))$("picker-panel").hidden=true;run();});
$("upload")?.addEventListener("change",inspectFile);$("import-confirm").addEventListener("click",importFile);$("cancel-import").addEventListener("click",()=>{$("mapping-panel").hidden=true;});
$("currency").addEventListener("change",()=>{if(state.result||state.holdings.length||state.demo){dirty();run();}});document.querySelectorAll('[name="selection"]').forEach(el=>el.addEventListener("change",()=>{if(state.result||state.holdings.length||state.demo){dirty();run();}}));
["seed","allow-stale"].forEach(id=>$(id).addEventListener("change",()=>{markCustom();queueRun();}));
$("distribution").addEventListener("toggle",renderHistogram);
$("download").addEventListener("click",()=>{if(state.result)Plotly.downloadImage("chart",{format:"png",width:1400,height:750,filename:`portfolio-simulation-${state.result.demo?"synthetic-example":state.result.currency}`});});
$("lookup-search").addEventListener("click",lookup);$("lookup-close").addEventListener("click",()=>{$("lookup").hidden=true;});
$("lookup-query").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();lookup();}});
// Recheck while the page is active; do not overwrite edited settings or holdings.
setInterval(()=>{if(state.result&&!state.demo&&!state.busy&&!state.running&&!document.hidden&&!$("results").classList.contains("outdated")&&$("mapping-panel").hidden)run();},15*60*1000);

function resetResults(){
  cancelBackground();
  state.result=null;state.selected=null;$("results").classList.remove("outdated");$("data-label").textContent="Holdings ready | Run to fetch closing prices";
  Plotly.purge("allocation-chart");$("allocation-panel").hidden=true;
  Plotly.purge("chart");$("chart").hidden=true;$("empty-chart").hidden=false;
  ["metrics","chart-legend","chart-footer","chart-navigation","selection-row","distribution","model-note","comparison-summary","backtest-summary"].forEach(id=>$(id).hidden=true);
  $("download").disabled=true;$("clear-path").hidden=true;$("median-return").textContent="";
}
const popularStocks=[['AAPL','Apple'],['MSFT','Microsoft'],['NVDA','Nvidia'],['AMZN','Amazon'],['GOOGL','Alphabet A'],['META','Meta'],['TSLA','Tesla'],['NFLX','Netflix'],['AMD','AMD'],['DIS','Disney']];
function addStock(stock){
  if(state.picked.some(h=>h.symbol===stock.symbol))return;
  if(state.picked.length>=10){$("stock-search-results").textContent="You can choose up to 10 stocks. Remove one to add another.";return;}
  state.picked.push({identifier:stock.symbol,symbol:stock.symbol,name:stock.name,quantity:1,declared_kind:"Stock"});renderPicker();
}
function renderPicker(){
  const popular=$("popular-stocks"),picked=$("picked-stocks");popular.replaceChildren();picked.replaceChildren();
  popularStocks.forEach(([symbol,name])=>{const selected=state.picked.some(h=>h.symbol===symbol),button=node("button",name);button.setAttribute("aria-pressed",String(selected));button.disabled=!selected&&state.picked.length>=10;button.addEventListener("click",()=>{if(selected){state.picked=state.picked.filter(h=>h.symbol!==symbol);renderPicker();}else addStock({symbol,name});});popular.append(button);});
  state.picked.forEach(h=>{const button=node("button",`${h.symbol} ×`);button.setAttribute("aria-label",`Remove ${h.symbol} from selection`);button.addEventListener("click",()=>{state.picked=state.picked.filter(x=>x.symbol!==h.symbol);renderPicker();});picked.append(button);});
  $("picked-count").textContent=`${state.picked.length} of 10 selected`;$("simulate-picked").disabled=!state.picked.length||state.busy;
}
async function searchStocks(){
  const query=$("stock-query").value.trim();if(!query)return;
  $("stock-search").disabled=true;$("stock-search-results").textContent="Searching…";
  try{
    const data=await api(`/api/search?q=${encodeURIComponent(query)}`);
    const stocks=data.results.filter(s=>s.kind==="Stock");$("stock-search-results").replaceChildren();
    if(!stocks.length)$("stock-search-results").textContent="No stocks found. Try a company name or ticker.";
    stocks.forEach(stock=>{const button=node("button",`${stock.symbol} | ${stock.name} | ${stock.exchange}`);button.addEventListener("click",()=>addStock(stock));$("stock-search-results").append(button);});
  }catch(e){$("stock-search-results").textContent=e.message;}finally{$("stock-search").disabled=false;}
}
$("choose-stocks")?.addEventListener("click",()=>{$("picker-panel").hidden=false;renderPicker();$("picker-panel").scrollIntoView({behavior:"smooth",block:"nearest"});});
$("picker-close")?.addEventListener("click",()=>{$("picker-panel").hidden=true;});
$("stock-search")?.addEventListener("click",searchStocks);
$("stock-query")?.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();searchStocks();}});
$("simulate-picked")?.addEventListener("click",()=>{
  if(!state.picked.length||state.picked.length>10||state.busy)return;
  state.holdings=state.picked.map(h=>({...h}));state.demo=false;state.importNote="Manually selected stocks, starting with one share each. Edit quantities here if needed.";
  resetResults();$("picker-panel").hidden=true;$("mapping-panel").hidden=true;$("lookup").hidden=true;
  document.querySelector('[name="selection"][value="All"]').checked=true;renderHoldings();run();
});

// Apply the same disabled states on the empty opening screen.
busy(false);
