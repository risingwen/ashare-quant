import {useEffect, useMemo, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import ReactECharts from 'echarts-for-react';
import './popularity.css';

const api=async(path:string)=>{const response=await fetch(`/api/v1${path}`);if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()};
const pct=(value:any)=>value==null?'—':`${Number(value)>0?'+':''}${Number(value).toFixed(2)}%`;

export default function Popularity(){
  const [source,setSource]=useState<'dc_hot'|'ths_hot'>('dc_hot');
  const [date,setDate]=useState('');
  const [selected,setSelected]=useState<any>(null);
  const sourceLabel=source==='dc_hot'?'东方财富':'同花顺';
  const dates=useQuery({queryKey:['popularity-dates',source],queryFn:()=>api(`/popularity/dates?source=${source}`)});
  useEffect(()=>{const latest=dates.data?.data?.[0]?.trade_date;if(latest&&!date)setDate(String(latest))},[dates.data,date]);
  const ranking=useQuery({queryKey:['rank',source,date],queryFn:()=>api(`/popularity/rankings?source=${source}&trade_date=${date}&limit=100`),enabled:!!date});
  const rows=ranking.data?.data||[];
  useEffect(()=>{if(rows.length&&!rows.some((row:any)=>row.symbol===selected?.symbol))setSelected(rows[0]);if(!rows.length)setSelected(null)},[ranking.data,selected?.symbol,rows]);
  const detail=useQuery({queryKey:['popularity-detail',source,date,selected?.symbol],queryFn:()=>api(`/popularity/detail/${selected.symbol}?source=${source}&end_date=${date}&days=30`),enabled:!!selected&&!!date});
  const bars=detail.data?.data?.bars||[];
  const ranks=detail.data?.data?.ranks||[];
  const window=detail.data?.window;
  const tradeDates=bars.map((row:any)=>String(row.trade_date));
  const rankByDate=useMemo(()=>new Map(ranks.map((row:any)=>[String(row.trade_date),row.rank])),[ranks]);
  const alignedRanks=tradeDates.map((tradeDate:string)=>rankByDate.get(tradeDate)??null);
  const changeSource=(next:'dc_hot'|'ths_hot')=>{setSource(next);setDate('');setSelected(null)};
  const anchorLine={symbol:['none','none'],silent:true,lineStyle:{color:'#f4bd62',type:'dashed',width:1},label:{show:true,formatter:'研究日',color:'#f4bd62',position:'insideEndTop'},data:[{xAxis:date}]};
  const commonXAxis={type:'category' as const,data:tradeDates,boundaryGap:true,axisLabel:{color:'#788797',hideOverlap:true},axisLine:{lineStyle:{color:'#26333e'}},axisTick:{show:false}};
  const klineOption={backgroundColor:'#0d141b',animation:false,textStyle:{color:'#788797'},grid:{left:56,right:18,top:24,bottom:44},tooltip:{trigger:'axis',axisPointer:{type:'cross'},backgroundColor:'#111b24',borderColor:'#2a3945',textStyle:{color:'#dce5ee'}},xAxis:commonXAxis,yAxis:{scale:true,axisLabel:{color:'#788797'},splitLine:{lineStyle:{color:'#1b2730'}}},series:[{name:'日K',type:'candlestick',data:bars.map((row:any)=>[row.open,row.close,row.low,row.high]),itemStyle:{color:'#ff6577',color0:'#3dd6a2',borderColor:'#ff6577',borderColor0:'#3dd6a2'},markLine:anchorLine}]};
  const rankOption={backgroundColor:'#0d141b',animation:false,textStyle:{color:'#788797'},grid:{left:48,right:18,top:20,bottom:44},tooltip:{trigger:'axis',backgroundColor:'#111b24',borderColor:'#2a3945',textStyle:{color:'#dce5ee'},formatter:(items:any[])=>{const item=items?.[0];return item?.value==null?`${item?.axisValue}<br/>未进入 Top100`:`${item.axisValue}<br/>最终排名：${item.value}`}},xAxis:commonXAxis,yAxis:{type:'value',inverse:true,min:1,max:100,axisLabel:{color:'#788797'},splitLine:{lineStyle:{color:'#1b2730'}}},series:[{name:'最终排名',type:'line',connectNulls:false,smooth:.2,symbolSize:6,data:alignedRanks,lineStyle:{color:'#54a7ff',width:2},itemStyle:{color:'#54a7ff'},areaStyle:{color:'rgba(84,167,255,.08)'},markLine:anchorLine}]};
  return <>
    <div className="page-title"><div><span className="eyebrow">POPULARITY SIGNALS</span><h1>人气研究</h1><p className="muted">榜单与价格共用 30 个交易日窗口 · 黄色虚线为当前研究日 · 未进入 Top100 的日期保留为空档</p></div><div className="popularity-controls"><div className="segmented source-switch"><button className={source==='dc_hot'?'active':''} onClick={()=>changeSource('dc_hot')}>东方财富</button><button className={source==='ths_hot'?'active':''} onClick={()=>changeSource('ths_hot')}>同花顺</button></div><select value={date} disabled={!dates.data?.data?.length} onChange={event=>{setDate(event.target.value);setSelected(null)}}><option value="" disabled>选择数据日期</option>{(dates.data?.data||[]).map((item:any)=><option value={item.trade_date} key={item.trade_date}>{item.trade_date}</option>)}</select></div></div>
    <div className="popularity-summary"><div><span>最终榜单</span><b>{rows.length} 条</b></div><div><span>当前选股</span><b>{selected?.name||'—'}</b><small>{selected?.symbol||'点击左侧榜单'}</small></div><div><span>研究日排名</span><b>{selected?.rank?`第 ${selected.rank} 名`:'—'}</b></div><div><span>图表窗口</span><b>{window?.trade_day_count||30} 个交易日</b><small>{window?`${window.start_date} — ${window.end_date}`:'围绕研究日自动定位'}</small></div></div>
    <div className="popularity-workbench">
      <section className="panel table-panel popularity-table"><div className="panel-head"><div><span className="section-kicker">FINAL SNAPSHOT</span><h2>最终榜单 Top100</h2></div><div><span className="chip source-chip">{sourceLabel}</span><span className="chip">{date}</span></div></div><div className="table-wrap"><table><thead><tr><th>排名</th><th>股票</th><th>次日</th><th>3日</th><th>5日</th><th>排名变化</th><th>热度</th></tr></thead><tbody>{rows.map((row:any)=><tr className={selected?.symbol===row.symbol?'selected':''} onClick={()=>setSelected(row)} key={`${row.endpoint}-${row.symbol}`}><td><b className="rank-number">{row.rank}</b></td><td><b>{row.name}</b><small>{row.symbol}</small></td><td className={row.next_day_return==null?'':Number(row.next_day_return)>=0?'rise':'fall'}><b>{pct(row.next_day_return)}</b><small>{row.next_trade_date||'待更新'}</small></td><td className={row.day_3_return==null?'':Number(row.day_3_return)>=0?'rise':'fall'}><b>{pct(row.day_3_return)}</b><small>{row.day_3_trade_date||'待更新'}</small></td><td className={row.day_5_return==null?'':Number(row.day_5_return)>=0?'rise':'fall'}><b>{pct(row.day_5_return)}</b><small>{row.day_5_trade_date||'待更新'}</small></td><td className={row.rank_change==null?'':Number(row.rank_change)>=0?'rise':'fall'}>{row.rank_change??'—'}</td><td>{row.heat??'—'}</td></tr>)}</tbody></table>{!rows.length&&<div className="empty">所选日期暂无最终榜单</div>}</div></section>
      <aside className="popularity-research-panel">
        <section className="panel chart-panel"><div className="panel-head"><div><span className="section-kicker">PRICE · ALIGNED 30 DAYS</span><h2>{selected?`${selected.name} K 线`:'点击榜单股票查看 K 线'}</h2></div><span className="chip">研究日 {date||'—'}</span></div>{bars.length?<ReactECharts style={{height:290}} option={klineOption}/>:<div className="empty-state">{selected?'暂无对应日线':'请先选择股票'}</div>}</section>
        <section className="panel chart-panel"><div className="panel-head"><div><span className="section-kicker">RANK · SAME TRADING DAYS</span><h2>{selected?`${sourceLabel}最终人气变化`:'人气变化'}</h2></div><span className="chip">低排名更热门</span></div>{bars.length?<ReactECharts style={{height:240}} option={rankOption}/>:<div className="empty-state">暂无可对齐的交易日</div>}</section>
      </aside>
    </div>
  </>;
}
