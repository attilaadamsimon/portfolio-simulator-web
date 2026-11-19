"use strict";
const experiment={automatic:true,preset:"history",revision:0,job:null,timer:null,normal:null,config:null,forecastYears:10};
const parameters={drift:.06,volatility:.20,jump_frequency:.5,jump_mean:-.15,jump_std:.10,kappa:2,theta_vol:.20,xi:.30,rho:-.6,block_months:1};
const extraFields=["jump_frequency","jump_mean","jump_std","kappa","theta_vol","xi","rho","block_months"];
const percentFields=new Set(["drift","volatility","jump_mean","jump_std","theta_vol"]);
const modelNames={gbm:"GBM",merton:"Merton",heston:"Heston",bootstrap:"Bootstrap"};
const help={gbm:"GBM uses correlated monthly log returns and constant volatility.",merton:"Merton adds shared market jumps to the correlated GBM paths. Jump sizes are log returns; compensation preserves the diffusion’s arithmetic expected return.",heston:"Heston gives each holding changing variance, with historical return correlations. Uses four full-truncation steps per month; this is an approximation, not an options-calibrated model.",bootstrap:"Bootstrap resamples historical monthly returns together across holdings. Example mode resamples synthetic history."};
const configuration=api('/api/model-options').then(data=>{experiment.config=data;return data;}).catch(error=>{message(`Could not load presets: ${error.message}`,true);return null;});
function parameterValue(id){return parameters[id];}
function setParameter(id,value){const scale=percentFields.has(id)?100:1;parameters[id]=Number((value*scale).toFixed(2))/scale;}
function chosenModels(){
  const primary=$('model').value;
  return $('compare-models').checked?[primary,...[...document.querySelectorAll('[name="compare-model"]:checked')].map(el=>el.value).filter(m=>m!==primary)]:[primary];
}
function activeExtraFields(){
  const selected=chosenModels();
  return [...(selected.includes('merton')?['jump_frequency','jump_mean','jump_std']:[]),...(selected.includes('heston')?['kappa','theta_vol','xi','rho']:[]),...(selected.includes('bootstrap')?['block_months']:[])];
}
function experimentSettings(){
  return {models:chosenModels(),scenario:$('scenario').value,backtest:$('backtest').checked,
    parameters:{...Object.fromEntries(activeExtraFields().map(id=>[id,parameterValue(id)])),drift:experiment.automatic?null:parameterValue('drift'),volatility:experiment.automatic?null:parameterValue('volatility')}};
}
function syncExperimentControls(){
  if(!$('model'))return;
  const models=chosenModels();
  $('compare-choices').hidden=!$('compare-models').checked;
  document.querySelectorAll('[name="compare-model"]').forEach(el=>{if(el.value===$('model').value)el.checked=true;el.disabled=state.busy||el.value===$('model').value;});
  $('model-help').textContent=models.map(m=>help[m]).join(' ');
  $('years').disabled=state.busy||$('backtest').checked;$('years-slider').disabled=$('years').disabled;
  $('preset-active').textContent=experiment.preset==='history'?'Historical fit':experiment.preset==='custom'?'Custom':experiment.config?.presets[experiment.preset]?.name||'Custom';
  document.querySelectorAll('[data-preset]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.preset===experiment.preset)));
  $('normal-settings').disabled=state.busy||$('scenario').value==='normal';
}
function markCustom(parameter=false){
  experiment.preset='custom';
  if(parameter)experiment.automatic=false;
  if(parameter&&$('scenario').value!=='normal'){
    $('scenario').value='normal';experiment.normal=null;
    $('scenario-note').textContent='Custom assumptions based on the previous stress settings.';
  }
  syncExperimentControls();
}
function queueRun(){
  dirty();clearTimeout(experiment.timer);
  experiment.timer=setTimeout(()=>{if(state.demo||state.holdings.length)run();},450);
}
function validExperiment(){
  const fields=['paths','seed'];
  if(!$('backtest').checked)fields.push('years');
  for(const id of fields){if($(id).value.trim()===''){message('Complete the simulation settings before running.',true);return false;}if(!$(id).checkValidity()){$(id).reportValidity();return false;}}
  if($('compare-models').checked&&chosenModels().length<2){message('Choose at least two models to compare.',true);return false;}
  return true;
}
function runBusy(on){
  state.running=on;$('results').setAttribute('aria-busy',String(on));
  $('loading-state').hidden=!on;$('run-status').hidden=!on;
  $('run').textContent=on?'Restart simulation':'Run simulation';
  $('run').disabled=!state.demo&&!state.holdings.length;
  $('download').disabled=on||!state.result||$('results').classList.contains('outdated');
  if(on){$('run-progress').value=0;$('run-message').textContent='Preparing simulation…';$('loading-text').textContent='Preparing simulation…';}
}
function cancelBackground(announce=false){
  ++experiment.revision;clearTimeout(experiment.timer);
  const key=experiment.job;experiment.job=null;
  if(key)api(`/api/jobs/${key}/cancel`,{method:'POST'}).catch(()=>{if(announce)message('Could not confirm cancellation with the server. Its result will be ignored.',true);});
  if(state.running)runBusy(false);
  if(announce){if(state.result)$('results').classList.add('outdated');$('download').disabled=true;message('Run cancelled. Any price request already in progress may finish before the server stops.');}
}
async function runBackground(refresh=false){
  if(state.busy)return;
  if(!state.demo&&!state.holdings.length){message('Upload holdings, choose stocks or use the example first.',true);return;}
  cancelBackground();
  if(!validExperiment())return;
  const revision=experiment.revision;
  const current=()=>revision===experiment.revision;
  runBusy(true);message();
  try{
    if(!state.demo&&state.holdings.some(h=>!h.symbol)){
      await resolveHoldings();if(!current())return;renderHoldings();
      if(state.holdings.some(h=>!h.symbol))throw new Error('No reliable listing was found for some positions. Use Find listing for those positions.');
    }
    const request=settings(refresh);
    const submitted=await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
    if(!current()){await api(`/api/jobs/${submitted.id}/cancel`,{method:'POST'});return;}
    experiment.job=submitted.id;
    const started=Date.now();
    while(current()){
      const job=await api(`/api/jobs/${submitted.id}`);if(!current())return;
      $('run-progress').value=job.progress;$('run-message').textContent=job.message;$('loading-text').textContent=job.message;
      if(job.status==='error')throw new Error(job.error);
      if(job.status==='cancelled'){message('Run cancelled.');break;}
      if(job.status==='done'){
        const result=job.result;state.result=result;state.selected=null;$('results').classList.remove('outdated');
        if(experiment.automatic){setParameter('drift',result.calibration.drift);setParameter('volatility',result.calibration.volatility);}
        await renderResult(result);if(!current())return;
        renderHoldings();message(result.warnings.join('\n'));break;
      }
      if(Date.now()-started>620000)throw new Error('This run took too long. Reduce paths or years and retry.');
      await new Promise(resolve=>setTimeout(resolve,500));
    }
  }catch(error){
    if(current()){
      const key=experiment.job;if(key)api(`/api/jobs/${key}/cancel`,{method:'POST'}).catch(()=>{});
      if(state.result)$('results').classList.add('outdated');
      message(error.name==='TimeoutError'?'The server did not respond. Please retry.':error.message,true);
    }
  }finally{if(current()){experiment.job=null;runBusy(false);syncExperimentControls();}}
}
function ordinal(value){const n=Math.round(value),s=n%100;return `${n}${s>=11&&s<=13?'th':({1:'st',2:'nd',3:'rd'}[n%10]||'th')}`;}
function decorateResults(traces,r){
  const models=r.comparisons||[r],c=colors(),palette=[c.accent,c.ink,c.highlight,c.muted],dashes=['solid','dash','dot','dashdot'];
  $('chart-note').textContent=`${r.paths.toLocaleString()} paths | ${r.years} year${r.years===1?'':'s'} | monthly observations | seed ${r.seed}${r.demo?' | synthetic example':''}`;
  $('model-note').hidden=false;$('model-note').textContent=`Summary and distribution: ${modelNames[r.model]||'GBM'}${r.backtest?' | held-out historical year':' | forecast'}${r.scenario&&r.scenario!=='normal'?' | stress scenario':''}`;
  const legend=$('chart-legend');legend.replaceChildren();
  if(models.length===1){legend.append(node('span','Median','median-key'),node('span','Middle 90%','band-key'));}
  else{
    traces.length=0;
    $('model-note').textContent+=' | Chart: median outcomes; ranges in the table below';
    models.forEach((m,i)=>{
      const item=node('button',undefined,'model-key quiet'),swatch=node('i',undefined,'model-swatch');
      item.dataset.modelTrace=String(i);item.setAttribute('aria-pressed','false');item.title=`Focus ${modelNames[m.model]}; click again to clear`;item.addEventListener('click',()=>highlightPath(i));
      swatch.style.borderTopColor=palette[i];swatch.style.borderTopStyle=i===0?'solid':i===1?'dashed':'dotted';
      item.append(swatch,document.createTextNode(modelNames[m.model]));legend.append(item);
      traces.push({x:r.time,y:m.bands['50'],name:`${modelNames[m.model]} median`,type:'scatter',mode:'lines+markers',
        marker:{size:r.time.map((_,j)=>j===r.time.length-1?7:0),color:palette[i]},
        line:{color:palette[i],width:2.8,dash:dashes[i]},meta:{baseWidth:2.8,baseColor:palette[i]},hovertemplate:`Year %{x:.1f}<br>%{y:,.0f} ${r.currency}<extra>${modelNames[m.model]} median</extra>`});
    });
  }
  $('comparison-summary').hidden=models.length<2;
  $('comparison-summary').replaceChildren(simpleTable(['Model','Median outcome','5th–95th percentile','Below start'],models.map(m=>[modelNames[m.model],`${money(m.median)} (${(m.median/m.initial-1)>=0?'+':''}${((m.median/m.initial-1)*100).toFixed(1)}%)`,`${money(m.p05)} – ${money(m.p95)}`,`${(m.loss_probability*100).toFixed(1)}%`])));
  $('backtest-summary').hidden=!r.backtest;
  if(r.backtest){
    const info=r.backtest_info,h=r.historical,name=info.synthetic?'Synthetic held-out path':'Historical portfolio replay';
    traces.push({x:r.time,y:h.values,name,type:'scatter',mode:'lines+markers',line:{color:c.ink,width:3,dash:'longdash'},marker:{size:h.values.map((_,i)=>i>0&&!h.inside[i-1]?7:0),color:c.highlight},meta:{baseWidth:3,baseColor:c.ink},hovertemplate:`%{y:,.0f} ${r.currency}<extra>${name}</extra>`});
    const actualKey=node('span',undefined,'model-key'),actualSwatch=node('i',undefined,'model-swatch');actualSwatch.style.borderTopColor=c.ink;actualSwatch.style.borderTopStyle='dashed';actualKey.append(actualSwatch,document.createTextNode(name));legend.append(actualKey);
    $('backtest-summary').textContent=`${info.synthetic?'Synthetic demonstration':`${info.test_start} to ${info.test_end}`} | fitted on ${info.training_months} earlier months (through ${info.train_end}).\n`+models.map(m=>`${modelNames[m.model]}: ${info.synthetic?'Synthetic':'Historical'} result landed at the ${ordinal(m.historical.percentile)} percentile of simulated outcomes; outside the pointwise 5th–95th range in ${m.historical.outside_months} of 12 months.`).join('\n');
  }
}
for(const id of ['years','paths']){
  for(const suffix of ['', '-slider'])$(id+suffix).addEventListener('input',()=>{
    const source=$(id+suffix),target=$(id+(suffix?'':'-slider'));target.value=source.value;
    markCustom();queueRun();
  });
}
$('model').addEventListener('change',()=>{if($('model').value!=='gbm')$('experiment-panel').open=true;document.querySelector(`[name="compare-model"][value="${$('model').value}"]`).checked=true;markCustom();queueRun();});
$('compare-models').addEventListener('change',()=>{markCustom();queueRun();});
document.querySelectorAll('[name="compare-model"]').forEach(el=>el.addEventListener('change',()=>{markCustom();queueRun();}));
$('backtest').addEventListener('change',()=>{
  if($('backtest').checked){experiment.forecastYears=Number($('years').value);$('years').value=1;}
  else $('years').value=experiment.forecastYears;
  $('years-slider').value=$('years').value;markCustom();queueRun();
});
$('cancel-run').addEventListener('click',()=>cancelBackground(true));
function snapshotAssumptions(){return {automatic:experiment.automatic,preset:experiment.preset,values:Object.fromEntries(['drift','volatility',...extraFields].map(id=>[id,parameterValue(id)]))};}
function restoreNormal(){
  $('scenario').value='normal';
  if(experiment.normal){const s=experiment.normal;experiment.automatic=s.automatic;experiment.preset=s.preset;Object.entries(s.values).forEach(([id,v])=>setParameter(id,v));experiment.normal=null;}
  $('scenario-note').textContent='No stress override. Scenarios are illustrative constant regimes, not exact event replays.';
  syncExperimentControls();
}
$('scenario').addEventListener('change',async()=>{
  const config=await configuration;if(!config)return;
  const key=$('scenario').value;
  if(key==='normal')restoreNormal();
  else{
    if(!experiment.normal)experiment.normal=snapshotAssumptions();
    const scenario=config.scenarios[key];Object.entries(scenario).filter(([k])=>k!=='name'&&k!=='note').forEach(([id,v])=>setParameter(id,v));
    experiment.automatic=false;experiment.preset='custom';$('scenario-note').textContent=`${scenario.note} Applied throughout the selected horizon. Return to normal restores your previous assumptions.`;
    syncExperimentControls();
  }
  queueRun();
});
$('normal-settings').addEventListener('click',()=>{restoreNormal();queueRun();});
$('historical-fit').addEventListener('click',()=>{
  restoreNormal();experiment.automatic=true;experiment.preset='history';
  syncExperimentControls();queueRun();
});
document.querySelectorAll('[data-preset]').forEach(button=>button.addEventListener('click',async()=>{
  const config=await configuration;if(!config)return;
  restoreNormal();experiment.normal=null;
  const key=button.dataset.preset,preset=config.presets[key];experiment.automatic=false;experiment.preset=key;
  Object.entries(config.defaults).forEach(([id,v])=>setParameter(id,v));
  for(const id of ['drift','volatility'])setParameter(id,preset[id]);setParameter('theta_vol',preset.volatility);
  $('backtest').checked=false;experiment.forecastYears=preset.years;
  for(const id of ['years','paths']){$(id).value=preset[id];$(id+'-slider').value=preset[id];}
  $('model').value='gbm';syncExperimentControls();queueRun();
}));
syncExperimentControls();
window.addEventListener('pagehide',()=>{if(experiment.job)navigator.sendBeacon(`/api/jobs/${experiment.job}/cancel`);});
