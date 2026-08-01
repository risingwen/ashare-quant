import {useEffect, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import ReactECharts from 'echarts-for-react';
import './popularity.css';

const api = async (path:string) => { const r=await fetch(`/api/v1${path}`); if(!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); };

export default function Popularity(){
  const [source,setSource]=useState<'dc_hot'|'ths_hot'>('dc_hot');
  const [date,setDate]=useState('');
  const sourceLabel=source==='dc_hot'?'东方财富':'同花顺';
  const dates=useQuery({queryKey:['popularity-dates',source],queryFn:()=>api(`/popularity/dates?source=${source}`)});
  useEffect(()=>{const latest=dates.data?.data?.[0]?.trade_date;if(latest&&!date)setDate(String(latest))},[dates.data,date]);
  const q=useQuery({queryKey:['rank',source,date],queryFn:()=>api(`/popularity/rankings?source=${source}&trade_date=${date}&limit=100`),enabled:!!date});
  const rows=q.data?.data||[];
  const chartRows=rows.slice(0,20);
  const changeSource=(next:'dc_hot'|'ths_hot')=>{setSource(next);setDate('')};
  return <><div className="page-title"><div><span className="eyebrow">POPULARITY SIGNALS</span><h1>人气研究</h1><p className="muted">东财 / 同花顺每日最终 Top100 · 两个榜单独立展示、不混合排名</p></div><div className="popularity-controls"><div className="segmented source-switch"><button className={source==='dc_hot'?'active':''} onClick={()=>changeSource('dc_hot')}>东方财富</button><button className={source==='ths_hot'?'active':''} onClick={()=>changeSource('ths_hot')}>同花顺</button></div><select value={date} disabled={!dates.data?.data?.length} onChange={e=>setDate(e.target.value)}><option value="" disabled>选择数据日期</option>{(dates.data?.data||[]).map((d:any)=><option value={d.trade_date} key={d.trade_date}>{d.trade_date}</option>)}</select></div></div>
    <div className="cards"><div className="card"><span>最终榜单记录</span><strong>{rows.length}</strong></div><div className="card"><span>榜单口径</span><strong>Top100</strong></div><div className="card"><span>榜首</span><strong>{rows[0]?.name||'—'}</strong></div><div className="card"><span>数据来源</span><strong>{rows.length?sourceLabel:'—'}</strong></div></div>
    <section className="panel chart-panel"><div className="panel-head"><div><span className="section-kicker">FINAL RANK</span><h2>最终人气 Top 20</h2></div></div><ReactECharts style={{height:340}} option={{backgroundColor:'#0d141b',textStyle:{color:'#788797'},grid:{left:48,right:24,top:20,bottom:56},tooltip:{trigger:'axis',backgroundColor:'#111b24',borderColor:'#2a3945',textStyle:{color:'#dce5ee'}},xAxis:{type:'category',axisLabel:{color:'#788797',rotate:30},axisLine:{lineStyle:{color:'#26333e'}},data:chartRows.map((r:any)=>r.name||r.symbol)},yAxis:{type:'value',inverse:true,min:1,axisLabel:{color:'#788797'},splitLine:{lineStyle:{color:'#1b2730'}}},series:[{type:'bar',itemStyle:{color:'#3dd6a2',borderRadius:[3,3,0,0]},data:chartRows.map((r:any)=>r.rank)}]}}/></section>
    <section className="panel table-panel popularity-table"><div className="panel-head"><div><span className="section-kicker">FINAL SNAPSHOT</span><h2>最终榜单 Top100</h2></div><div><span className="chip source-chip">{sourceLabel}</span><span className="chip">{date}</span></div></div><div className="table-wrap"><table><thead><tr><th>排名</th><th>股票</th><th>来源</th><th>排名变化</th><th>热度</th><th>上榜说明</th><th>数据日期</th></tr></thead><tbody>{rows.map((r:any)=><tr key={`${r.endpoint}-${r.symbol}`}><td><b className="rank-number">{r.rank}</b></td><td><b>{r.name}</b><small>{r.symbol}</small></td><td><span className="source-badge">{sourceLabel}</span><small>{r.endpoint}</small></td><td className={r.rank_change==null?'':Number(r.rank_change)>=0?'rise':'fall'}>{r.rank_change??'—'}</td><td>{r.heat??'—'}</td><td>{r.rank_reason||r.concept||'—'}</td><td>{r.trade_date}</td></tr>)}</tbody></table></div></section></>;
}
