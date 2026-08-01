import {useEffect, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import ReactECharts from 'echarts-for-react';
import './moneyflow.css';

const api=async(path:string)=>{const r=await fetch(`/api/v1${path}`);if(!r.ok){const body=await r.json().catch(()=>null);throw new Error(body?.detail?.message||`HTTP ${r.status}`)}return r.json()};
const money=(v:any)=>v==null?'—':`${Number(v)>=0?'+':''}${(Number(v)/1e8).toFixed(2)}亿`;

export default function MoneyFlow(){
  const [scope,setScope]=useState<'stock'|'sector'>('stock');
  const [minDays,setMinDays]=useState(5);
  const [date,setDate]=useState('');
  const [selected,setSelected]=useState<any>(null);
  const dates=useQuery({queryKey:['moneyflow-dates'],queryFn:()=>api('/moneyflow/dates'),refetchInterval:30000});
  useEffect(()=>{const latest=dates.data?.data?.[0]?.trade_date;if(latest&&!date)setDate(String(latest))},[dates.data,date]);
  const streaks=useQuery({queryKey:['moneyflow-streaks',scope,date,minDays],queryFn:()=>api(`/moneyflow/streaks?scope=${scope}&end_date=${date}&days=5&min_inflow_days=${minDays}&limit=300`),enabled:!!date});
  const history=useQuery({queryKey:['moneyflow-history',scope,selected?.code],queryFn:()=>api(`/moneyflow/history/${selected.code}?scope=${scope}&limit=20`),enabled:!!selected});
  const rows=streaks.data?.data||[]; const series=[...(history.data?.data||[])].reverse();
  const total=rows.reduce((s:number,r:any)=>s+Number(r.net_amount_sum||0),0);
  const effectiveDate=streaks.data?.effective_end_date||date;
  const windowDates=(streaks.data?.window_dates||[]).join('、');
  return <><div className="page-title"><div><span className="eyebrow">CAPITAL FLOW SCREENER</span><h1>资金流查询</h1><p className="muted">东方财富口径 · 仅按已有交易日筛选，不自动回退日期</p></div><label className="flow-date"><span>数据交易日</span><select value={date} disabled={dates.isLoading||!dates.data?.data?.length} onChange={e=>{setDate(e.target.value);setSelected(null)}}><option value="" disabled>选择交易日</option>{(dates.data?.data||[]).map((d:any)=><option value={d.trade_date} key={d.trade_date}>{d.trade_date}</option>)}</select></label></div>
    <div className="flow-toolbar"><div className="segmented"><button className={scope==='stock'?'active':''} onClick={()=>{setScope('stock');setSelected(null)}}>个股</button><button className={scope==='sector'?'active':''} onClick={()=>{setScope('sector');setSelected(null)}}>板块</button></div><div className="segmented"><button className={minDays===5?'active':''} onClick={()=>setMinDays(5)}>连续 5 日流入</button><button className={minDays===4?'active':''} onClick={()=>setMinDays(4)}>近 5 日至少 4 日流入</button></div><span className="chip">moneyflow_{scope==='stock'?'dc':'ind_dc'}</span></div>
    <div className="metric-grid"><div className="metric"><span>符合条件</span><strong>{rows.length}</strong><small>{scope==='stock'?'只个股':'个板块'}</small></div><div className="metric"><span>实际数据截止日</span><strong>{effectiveDate||'—'}</strong><small title={windowDates}>最近 5 个真实交易日</small></div><div className="metric good"><span>合计净流入</span><strong>{money(total)}</strong><small>窗口累计</small></div><div className="metric"><span>当前条件</span><strong>{minDays} / 5</strong><small>资金净流入天数</small></div></div>
    {streaks.isError&&<div className="flow-error">{streaks.error instanceof Error?streaks.error.message:'查询失败，请重新选择交易日'}</div>}
    <div className="flow-grid"><section className="panel table-panel"><div className="panel-head"><div><span className="section-kicker">FLOW STREAKS</span><h2>{scope==='stock'?'个股':'板块'}连续流入排行</h2></div></div><div className="table-wrap"><table><thead><tr><th>排名</th><th>{scope==='stock'?'股票':'板块'}</th><th>流入天数</th><th>5日累计净流入</th><th>平均净占比</th><th>最新净流入</th><th>最新涨跌幅</th></tr></thead><tbody>{rows.map((r:any,i:number)=><tr className={selected?.code===r.code?'selected':''} onClick={()=>setSelected(r)} key={r.code}><td className="rank-number">{i+1}</td><td><b>{r.name}</b><small>{r.code}</small></td><td><span className="status success">{r.inflow_days} / 5</span></td><td className={Number(r.net_amount_sum)>=0?'rise':'fall'}>{money(r.net_amount_sum)}</td><td>{Number(r.avg_net_amount_rate||0).toFixed(2)}%</td><td className={Number(r.latest_net_amount)>=0?'rise':'fall'}>{money(r.latest_net_amount)}</td><td className={Number(r.latest_pct_change)>=0?'rise':'fall'}>{Number(r.latest_pct_change||0).toFixed(2)}%</td></tr>)}</tbody></table>{!rows.length&&!streaks.isLoading&&<div className="empty">当前条件暂无结果或历史数据仍在回补</div>}</div></section>
      <aside className="panel flow-detail"><div className="panel-head"><div><span className="section-kicker">20 DAY HISTORY</span><h2>{selected?`${selected.name} · 资金趋势`:'选择一个标的'}</h2></div></div>{!selected?<div className="empty">点击左侧记录查看每日资金流</div>:<><ReactECharts style={{height:260}} option={{backgroundColor:'transparent',grid:{left:48,right:15,top:20,bottom:42},tooltip:{trigger:'axis'},xAxis:{type:'category',axisLabel:{color:'#788797',rotate:35},data:series.map((r:any)=>r.trade_date)},yAxis:{type:'value',axisLabel:{color:'#788797',formatter:(v:number)=>`${(v/1e8).toFixed(1)}亿`},splitLine:{lineStyle:{color:'#1b2730'}}},series:[{type:'bar',data:series.map((r:any)=>({value:r.net_amount,itemStyle:{color:Number(r.net_amount)>=0?'#ff6577':'#35c98a'}}))}]}}/><table><thead><tr><th>日期</th><th>净流入</th><th>净占比</th></tr></thead><tbody>{[...series].reverse().slice(0,8).map((r:any)=><tr key={r.trade_date}><td>{r.trade_date}</td><td className={Number(r.net_amount)>=0?'rise':'fall'}>{money(r.net_amount)}</td><td>{Number(r.net_amount_rate||0).toFixed(2)}%</td></tr>)}</tbody></table></>}</aside>
    </div></>;
}
