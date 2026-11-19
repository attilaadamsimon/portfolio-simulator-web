"use strict";
function compactChartMarkers(traces, currency){
  const x=[],y=[],sizes=[],colors=[],targets=[];
  const lines=traces.map((trace,index)=>{
    if(trace.mode!=="lines+markers")return trace;
    const marker=trace.marker||{};
    trace.x.forEach((value,i)=>{
      const size=Array.isArray(marker.size)?marker.size[i]:marker.size;
      if(!(size>0))return;
      x.push(value);y.push(trace.y[i]);sizes.push(size);
      colors.push(Array.isArray(marker.color)?marker.color[i]:marker.color);
      targets.push([index,trace.name]);
    });
    const line={...trace,mode:"lines"};delete line.marker;return line;
  });
  if(x.length)lines.push({x,y,type:"scatter",mode:"markers",showlegend:false,
    marker:{size:sizes,color:colors},customdata:targets,meta:{markerTargets:true},
    hovertemplate:`Year %{x:.1f}<br>%{y:,.0f} ${currency}<extra>%{customdata[1]}</extra>`});
  return lines;
}
